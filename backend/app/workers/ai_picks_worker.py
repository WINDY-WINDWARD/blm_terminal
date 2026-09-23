import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ai_picks import AIPick, PickStatus, PickDirection, AIPickTrace
import time
from app.workers.lifecycle import _startup_pipeline_done
from app.services.llm_provider import stream_chat_completion
from app.services.ai_chat_service import BLM_TOOLS, _run_tools_parallel

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_LAST_SUCCESS_KEY = "ai_picks.last_success_date"  # IST YYYY-MM-DD of last run yielding >=1 pick
_LAST_EVAL_KEY = "ai_picks.last_eval_date"  # IST YYYY-MM-DD of last evaluator pass
_STALE_SECTOR_HOURS = 48


def _today_ist_str(now: datetime | None = None) -> str:
    """Current date in Asia/Kolkata as YYYY-MM-DD."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(_IST).strftime("%Y-%m-%d")


def _past_market_hours(now: datetime | None = None) -> bool:
    """True at/after the 15:30 IST close (any day — weekends count as closed)."""
    now = now or datetime.now(timezone.utc)
    ist = now.astimezone(_IST)
    return (ist.hour, ist.minute) >= (15, 30)


def _morning_due(last_success: str | None, today: str) -> bool:
    """Pure decision: run the morning hunter iff no successful run today."""
    return last_success != today


def _evening_due(last_eval: str | None, today: str, has_picks_today: bool, past_hours: bool) -> bool:
    """Pure decision: evaluate iff picks exist today, none evaluated, past close."""
    return bool(has_picks_today and past_hours and last_eval != today)


async def _get_config_value(db: AsyncSession, key: str) -> str | None:
    try:
        from app.models.system_config import SystemConfig
        res = await db.execute(select(SystemConfig.value).where(SystemConfig.key == key))
        row = res.first()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"Failed to read system_config {key}: {e}")
        return None


async def _set_config_value(db: AsyncSession, key: str, value: str) -> None:
    from app.models.system_config import SystemConfig
    res = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    row = res.scalars().first()
    if row is None:
        db.add(SystemConfig(key=key, value=value))
    else:
        row.value = value
    await db.commit()


def _ist_day_utc_bounds(today_str: str) -> tuple[datetime, datetime]:
    """UTC [start, end) bounds for an IST calendar day (naive, SQLite-style)."""
    start_ist = datetime.strptime(today_str, "%Y-%m-%d").replace(tzinfo=_IST)
    start_utc = start_ist.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, start_utc + timedelta(days=1)


async def _picks_created_today(db: AsyncSession, today: str) -> bool:
    """Any NEW/ACTED_ON pick created today (IST)?"""
    start_utc, end_utc = _ist_day_utc_bounds(today)
    res = await db.execute(
        select(AIPick.id)
        .where(AIPick.created_at >= start_utc, AIPick.created_at < end_utc)
        .where(AIPick.status.in_([PickStatus.NEW, PickStatus.ACTED_ON]))
        .limit(1)
    )
    return res.first() is not None

async def get_dynamic_models():
    """Fetch hunter and verifier models.

    The user picks both explicitly — in the first-launch setup wizard or in
    Settings → AI → Background Worker Models — stored as ai.hunter_model /
    ai.verifier_model. The hardcoded values below are last-resort fallbacks
    used only when nothing has been picked yet.
    """
    hunter = "kimi-k2.6"
    verifier = "minimax-m2.5"
        
    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(SystemConfig).where(SystemConfig.key.in_(["ai.hunter_model", "ai.verifier_model"])))
            configs = {c.key: c.value for c in res.scalars().all()}
            if configs.get("ai.hunter_model"):
                hunter = configs["ai.hunter_model"]
            if configs.get("ai.verifier_model"):
                verifier = configs["ai.verifier_model"]
    except Exception as e:
        logger.warning("Failed to fetch dynamic AI models: %s", e)
        
    return hunter, verifier





# Bullet-proof System Prompts
HUNTER_PROMPT = """<persona>
You are 'The Hunter', an elite, quantitative equity research AI specializing in actionable mid-cap swing trades on the NSE. Your expertise lies in combining technical momentum with fundamental catalysts to identify high-probability setups with >2:1 Risk/Reward.
</persona>

<context>
You are operating within an autonomous agentic loop. You must proactively use the provided tools to gather live market data. Evaluate each data point in your thought process to decide on your next tool call before arriving at your final answer.
</context>

<task>
Execute a deep market scan across the NSE to identify exactly 4 to 6 highly actionable mid-cap swing trade setups.

Workflow Directives:
1. DISCOVERY: Call `get_global_notifications` and `get_volume_gainers` to identify stocks with recent technical breakouts or abnormal volume surges.
2. SCREENING: Call `run_tql_screener` with strict momentum filters (e.g., RSI > 55, MACDHist > 0, From52wHigh > -15) to narrow down candidates.
3. NEWS (YOUR JOB — the injected context contains NO news): Call `get_global_news` yourself for the macro regime, then `get_company_news` for EVERY shortlisted candidate. Never present a pick whose catalyst you have not read firsthand. Confirm positive catalysts and avoid adverse events with `get_upcoming_events` and `get_recent_announcements`.
4. SECTOR CHECK: The injected snapshot lists top/bottom industries and sectors. Drill into your candidates' sectors with `list_industries`/`list_sectors` → `get_industry_stocks`/`get_sector_stocks` to confirm sector tailwinds.
5. SYNTHESIS: Select the absolute best 4-6 setups. Discard weak setups.
</task>

<tool_usage_guidelines>
- Use `get_global_notifications` for real-time alerts and `get_volume_gainers` for volume surges.
- If `get_company_news` fails or returns insufficient data, immediately fallback to `company_fdm` to check recent corporate announcements.
- Do not guess parameter values (e.g., sector slugs). If you need an industry list, call `list_industries` first.
</tool_usage_guidelines>

<freshness_rules>
- The injected breadth snapshot is stamped with as-of times; sector/industry rows carry their own `last_updated`.
- FRESHNESS IS MANDATORY: cite the as-of time for EVERY data claim in your thesis. Treat sector/industry data older than 48 hours as STALE: say so explicitly and prefer a fresher cross-check (technicals, news, events).
- Never invent market context. Every claim must trace to a tool output you actually called.
</freshness_rules>

<format>
For each selected pick, your thesis MUST include:
- Technical Setup (support/resistance, moving averages, volume, chart pattern).
- Catalysts (sentiment, recent news, upcoming events).
- Expected Timeframe (typically 3-7 trading days).
- Precise Entry, Take Profit, and Stop Loss based on real support/resistance levels.

CRITICAL FINAL OUTPUT:
When you have finished all tool calls and are ready to finalize your answer, you MUST output your final picks strictly as a JSON array enclosed within a <picks> XML tag.

<picks>
[
  {
    "symbol": "TICKER",
    "direction": "LONG",
    "entry": 100.50,
    "take_profit": 110.00,
    "stop_loss": 95.00,
    "thesis": "[Detailed Analysis] Technicals: Price broke above 100-level resistance with volume surge. Entry at 100.50 places stop below support at 95. Target 110 gives 2.9:1 RR. Catalyst: Contract win news. Timeframe: 5-7 days."
  }
]
</picks>
</format>
"""

VERIFIER_PROMPT = """<persona>
You are 'The Verifier', a strict Chief Risk Officer AI. You operate with absolute discipline and are highly averse to uncalculated risk.
</persona>

<context>
The Hunter AI has provided a list of proposed mid-cap swing trade setups. Your job is to independently verify them using your available tools. You serve as a strict filter to protect capital.
</context>

<task>
1. Independently verify the technicals, fundamentals, news, and fair value of each proposed setup.
2. Re-pull `get_company_news` yourself for EVERY proposed pick — never trust the Hunter's news summary. Call tools like `get_symbol_data`, `company_fdm`, `get_upcoming_events`, and `get_recent_announcements` to check for red flags.
3. Sanity-check each pick against its sector: confirm the industry/sector trend supports (or at least does not contradict) the setup.
4. REJECT any setup that has poor financials, bad news sentiment, or overextended technicals.
5. Keep only the absolute best 2 to 3 setups. If none pass your strict criteria, return an empty array.
</task>

<tool_usage_guidelines>
- If `get_company_news` fails or returns insufficient data, immediately fallback to `company_fdm` to check recent corporate announcements.
</tool_usage_guidelines>

<freshness_rules>
- FRESHNESS IS MANDATORY: cite the as-of time (`last_updated`) for every dataset you rely on. Sector/industry data older than 48 hours is STALE — say so explicitly and prefer fresher cross-checks.
- Never invent market context. Every claim must trace to a tool output you actually called.
</freshness_rules>

<format>
CRITICAL FINAL OUTPUT:
Output your final approved list of 2-3 setups strictly as a JSON array inside a <verified_picks> XML tag. Use the exact same JSON object structure as the input, but update the 'thesis' field to append your verification notes.

<verified_picks>
[
  {
    "symbol": "TICKER",
    "direction": "LONG",
    "entry": 100.50,
    "take_profit": 115.00,
    "stop_loss": 96.00,
    "note": "Verified: Solid fundamentals (no downgrade risk), technicals intact (support at 96 holds). Adjusted TP to 115 for better R:R (3.1:1). Thesis preserved.",
    "verdict": "BULLISH",
    "technical": "Support at 96 strong; RSI consolidating above 50. Breakout setup intact.",
    "fundamental": "No adverse news; P/E within peer range.",
    "catalyst": "Upcoming event in 2 weeks; good timing for swing trade.",
    "risk": "If support at 96 breaks on volume, thesis invalidated.",
    "action": "BUY"
  }
]
</verified_picks>
</format>
"""

EVALUATOR_PROMPT = """You are 'The Evaluator', a portfolio management AI specializing in swing trades.
Your objective: Re-evaluate active swing trade positions based on today's price action and news, with patience and discipline.
You will be given the current state of a pick. 

CRITICAL INSTRUCTIONS:
1. PATIENCE WITH UNFILLED SETUPS: If a position has NOT YET hit its entry or stop loss, treat this as NORMAL and expected. Most swing trades take 3-7 trading days to develop. Default to HOLD unless:
   - The entry price has been surpassed in an adverse direction (price is far below entry for LONG, or far above entry for SHORT).
   - OR fundamental thesis has completely deteriorated (major adverse news, earnings miss, downgrade).
   - OR technical structure has fully broken (support broken cleanly on high volume, reversal patterns confirmed).

2. EVALUATE TODAY'S CONTEXT:
    - Use your tools to check today's closing price, recent news (`get_company_news`), and technicals for the given symbol.
    - Assess if the thesis remains intact, targets need adjustment, or position must close.
    - Compare current price action to the entry point and stop loss level.
    - FRESHNESS IS MANDATORY: cite the `last_updated` as-of time for all data used; treat sector/industry data older than 48 hours as stale.

3. DECISION LOGIC:
   - HOLD: Setup is progressing normally, no adverse signals, OR position not yet triggered.
   - ADJUST: Price is moving favorably; consider tightening stops or raising targets.
   - CLOSE: Clear evidence of thesis breakdown OR stop loss hit OR price invalidates technical structure.

4. Output your evaluation strictly as a JSON object inside an <evaluation> XML tag.

OUTPUT FORMAT:
<evaluation>
{
  "note": "Price consolidating near entry at 98.50. RSI in overbought territory but thesis intact. No adverse news.",
  "verdict": "NEUTRAL",
  "technical": "Consolidation pattern forming; watch for breakout above 102.",
  "fundamental": "No change in thesis; waiting for price confirmation.",
  "catalyst": "Earnings expected in 2 weeks; thesis still stands.",
  "risk": "If price breaks below 96.00 on volume, thesis is broken.",
  "action": "HOLD" // or "ADJUST" or "CLOSE" only if thesis is fundamentally broken
}
</evaluation>
"""


def _calculate_business_days_elapsed(start_dt: datetime, end_dt: datetime = None) -> int:
    """Calculate the number of business days (excluding weekends) between two datetimes.
    
    Counts only fully elapsed calendar days (does not include the current/end day).
    
    Args:
        start_dt: The start datetime (typically when the pick was created).
        end_dt: The end datetime (defaults to now in UTC).
    
    Returns:
        Number of business days (Mon-Fri only) fully elapsed since creation.
    """
    if end_dt is None:
        end_dt = datetime.now(timezone.utc)
    
    # Ensure both are timezone-aware
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    
    business_days = 0
    current = (start_dt + timedelta(days=1)).date()
    end_date = end_dt.date()
    
    # Count only fully elapsed business days between creation day and end day
    while current < end_date:
        # weekday() returns 0-6 (Mon-Sun), so Mon-Fri are 0-4
        if current.weekday() < 5:
            business_days += 1
        current += timedelta(days=1)
    
    return business_days


async def _save_trace(db: AsyncSession, symbol: str, role: str, prompt: str, response: str, duration_ms: int, status: str, err: str | None = None):
    try:
        trace = AIPickTrace(
            symbol=symbol,
            agent_role=role,
            prompt=prompt,
            response=response,
            duration_ms=duration_ms,
            status=status,
            error_message=err
        )
        db.add(trace)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to save AI trace: {e}")


def _extract_json_block(content: str, tag: str) -> dict | list:
    """Safely extract JSON from within XML-style tags, handling markdown code blocks."""
    # Find the LAST occurrence of the tags to avoid matching conversational mentions
    start_idx = content.rfind(f"<{tag}>")
    end_idx = content.rfind(f"</{tag}>")
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        content = content[start_idx + len(f"<{tag}>"):end_idx].strip()
    
    # Use regex to find the innermost JSON if it's wrapped in markdown
    match = re.search(r"```(?:json)?\n?(.*?)\n?```", content, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        json_str = content.strip()
        
    return json.loads(json_str)



async def _run_agent_loop(messages: list[dict], model: str, system_prompt: str | None = None) -> str:
    seen_calls = set()
    async def executor(tool_calls: list[dict]) -> tuple[list[str], list[dict]]:
        return await _run_tools_parallel(tool_calls, seen_calls)
        
    full_content = ""
    async for chunk in stream_chat_completion(
        messages=messages,
        model=model,
        tools=BLM_TOOLS,
        tool_executor=executor,
        system_prompt=system_prompt,
        max_iter=60
    ):
        evt = json.loads(chunk)
        if evt["type"] == "token":
            full_content += evt["text"]
        elif evt["type"] == "error":
            raise RuntimeError(f"Antigravity API error: {evt['message']}")
            
    return full_content


async def _run_agent_loop_retry(
    messages: list[dict],
    model: str,
    system_prompt: str | None,
    label: str,
    attempts: int = 3,
) -> str:
    """Run the agent loop, retrying transport/API errors (429, tokens, network).

    Parse errors are NOT retried here — they surface from _extract_json_block
    in the caller, where retrying cannot help.
    """
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return await _run_agent_loop(messages, model, system_prompt)
        except Exception as e:
            last_err = e
            logger.warning(f"{label} attempt {i + 1}/{attempts} failed: {e}")
            if i < attempts - 1:
                await asyncio.sleep(2.0 * (2 ** i))
    assert last_err is not None
    raise last_err


async def _call_hunter(db: AsyncSession, market_context: str = "") -> tuple[list[dict], str | None]:
    """Loop 1: Run hunt for picks. Returns (picks, error). Empty+None = no setups (legit)."""
    logger.info("Loop 1: Hunter starting")
    start_time = time.time()

    sys_prompt = HUNTER_PROMPT + "\n\n" + market_context
    messages = [{"role": "user", "content": "Execute your market scan and provide the top 2-3 swing trade picks."}]

    hunter_model, verifier_model = await get_dynamic_models()
    full_prompt = sys_prompt + "\n\n" + json.dumps(messages)
    try:
        text = await _run_agent_loop_retry(
            messages=messages,
            model=hunter_model,
            system_prompt=sys_prompt,
            label="Hunter",
        )
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        await _save_trace(db, "MULTI", "HUNTER", full_prompt, "", duration, "FAILED", str(e))
        return [], f"Hunter API failed after retries: {e}"

    duration = int((time.time() - start_time) * 1000)
    await _save_trace(db, "MULTI", "HUNTER", full_prompt, text, duration, "SUCCESS")

    try:
        return _extract_json_block(text, "picks"), None
    except Exception as e:
        logger.error(f"Hunter parsing failed: {e}. Raw content: {text}")
        return [], f"Hunter output unparseable: {e}"


async def _call_verifier(db: AsyncSession, proposed_picks: list[dict], market_context: str = "") -> tuple[list[dict], str | None]:
    """Loop 2: Run verify picks. Returns (picks, error). Empty+None = all rejected (legit)."""
    logger.info("Loop 2: Verifier starting")
    start_time = time.time()

    sys_prompt = VERIFIER_PROMPT + "\n\n" + market_context
    user_msg = f"Here are the proposed setups. Verify them carefully:\n{json.dumps(proposed_picks, indent=2)}"
    messages = [{"role": "user", "content": user_msg}]

    hunter_model, verifier_model = await get_dynamic_models()
    full_prompt = sys_prompt + "\n\n" + json.dumps(messages)
    try:
        text = await _run_agent_loop_retry(
            messages=messages,
            model=verifier_model,
            system_prompt=sys_prompt,
            label="Verifier",
        )
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        await _save_trace(db, "MULTI", "VERIFIER", full_prompt, "", duration, "FAILED", str(e))
        return [], f"Verifier API failed after retries: {e}"

    duration = int((time.time() - start_time) * 1000)
    await _save_trace(db, "MULTI", "VERIFIER", full_prompt, text, duration, "SUCCESS")

    try:
        return _extract_json_block(text, "verified_picks"), None
    except Exception as e:
        logger.error(f"Verifier parsing failed: {e}. Raw content: {text}")
        return [], f"Verifier output unparseable: {e}"


async def _call_evaluator(db: AsyncSession, pick_data: dict, market_context: str = "") -> dict:
    """Loop 3: Run evaluator for an existing pick (HOLD stays the safe default)."""
    start_time = time.time()

    sys_prompt = EVALUATOR_PROMPT + "\n\n" + market_context
    user_msg = f"Re-evaluate this active position:\n{json.dumps(pick_data, indent=2)}"
    messages = [{"role": "user", "content": user_msg}]

    hunter_model, verifier_model = await get_dynamic_models()
    full_prompt = sys_prompt + "\n\n" + json.dumps(messages)
    try:
        text = await _run_agent_loop_retry(
            messages=messages,
            model=verifier_model,
            system_prompt=sys_prompt,
            label=f"Evaluator {pick_data.get('symbol', 'UNKNOWN')}",
        )
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        await _save_trace(db, pick_data.get("symbol", "UNKNOWN"), "EVALUATOR", full_prompt, "", duration, "FAILED", str(e))
        return {"note": f"Evaluation failed due to API error: {str(e)}", "action": "HOLD"}

    duration = int((time.time() - start_time) * 1000)
    await _save_trace(db, pick_data.get("symbol", "UNKNOWN"), "EVALUATOR", full_prompt, text, duration, "SUCCESS")

    try:
        return _extract_json_block(text, "evaluation")
    except Exception as e:
        logger.error(f"Evaluator parsing failed: {e}. Raw content: {text}")

    return {"note": "Failed to generate evaluation.", "action": "HOLD"}



from app.mcp_server import get_top_gainers, get_top_losers, get_volume_gainers, list_sectors, list_industries


def _spread(row: dict) -> float:
    try:
        return float(row.get("advance") or 0) - float(row.get("decline") or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_breadth_row(row: dict) -> str:
    return (
        f"- {row.get('name')} (slug: {row.get('slug')}): "
        f"adv {row.get('advance')}/dec {row.get('decline')}, "
        f"sentiment {row.get('sentiment')}, PE {row.get('pe')}, "
        f"earnings YoY {row.get('earnings_yoy')}% "
        f"— as of {row.get('last_updated') or 'unknown'}"
    )


async def _fetch_market_context() -> str:
    """Deterministic breadth snapshot. Every section carries its as-of time.

    News is deliberately NOT included here — the agents fetch it themselves
    via get_global_news / get_company_news tools (fresher + per-symbol).
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    context_parts = ["### MARKET BREADTH SNAPSHOT ###"]

    # 1. Top Gainers & Losers (live snapshot — no stored timestamp available)
    try:
        gainers = await get_top_gainers(category="allSec")
        losers = await get_top_losers(category="allSec")

        g_symbols = [g.get('symbol', '') for g in gainers[:5]]
        l_symbols = [l.get('symbol', '') for l in losers[:5]]

        context_parts.append(f"Top Gainers (live, fetched {now_utc}): {', '.join(g_symbols)}")
        context_parts.append(f"Top Losers (live, fetched {now_utc}): {', '.join(l_symbols)}")
    except Exception as e:
        logger.error(f"Failed to fetch market gainers/losers: {e}")

    # 2. Volume Surge (live snapshot)
    try:
        vol = await get_volume_gainers()
        items = vol if isinstance(vol, list) else vol.get('data', [])
        v_symbols = [v.get('symbol', '') for v in items[:5]]
        context_parts.append(f"Volume Surges (live, fetched {now_utc}): {', '.join(v_symbols)}")
    except Exception as e:
        logger.error(f"Failed to fetch volume gainers: {e}")

    # 3. Sector & Industry breadth (stored snapshot — stamped per row)
    try:
        for label, rows in (("SECTORS", await list_sectors()), ("INDUSTRIES", await list_industries())):
            ranked = sorted(rows, key=_spread, reverse=True)
            if not ranked:
                continue
            lines = [f"### {label} BREADTH (top/bottom 3 by advance-decline spread) ###"]
            for row in ranked[:3] + ranked[-3:]:
                lines.append(_format_breadth_row(row))
            context_parts.append("\n".join(lines))
    except Exception as e:
        logger.error(f"Failed to fetch sector/industry breadth: {e}")

    return "\n\n".join(context_parts)


async def run_loop_1_and_2(late: bool = False) -> str:
    """Execute Hunter (8am) and Verifier pipelines.

    Returns "ok" (>=1 pick saved), "empty" (legit: no setups / all rejected),
    or "error:<detail>" (API/parse failure — caller must report failed, and
    the success date stays unwritten so the next boot retries).
    """
    _, verifier_model = await get_dynamic_models()
    market_context = await _fetch_market_context()
    today = _today_ist_str()
    if late:
        market_context += (
            f"\n\nNOTE: This is a late catch-up run for {today} (the scheduled "
            "8am run was missed). Data may be less fresh than a morning run — "
            "say so where relevant and prefer the freshest cross-checks."
        )

    async with AsyncSessionLocal() as db:
        proposed_picks, hunter_err = await _call_hunter(db, market_context)
        if hunter_err:
            logger.error(f"Loop 1 failed: {hunter_err}")
            return f"error:{hunter_err}"
        if not proposed_picks:
            logger.info("Loop 1 found no valid setups today.")
            return "empty"

        verified_picks, verifier_err = await _call_verifier(db, proposed_picks, market_context)
        if verifier_err:
            logger.error(f"Loop 2 failed: {verifier_err}")
            return f"error:{verifier_err}"
        if not verified_picks:
            logger.info("Loop 2 rejected all setups.")
            return "empty"

        # Commit to DB
        for pick in verified_picks:
            try:
                notes = []
                if late:
                    notes.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "note": f"Catch-up run for {today} (scheduled 8am run missed). Freshness reduced; verify before acting.",
                        "model": "system",
                        "late": True,
                    })
                new_pick = AIPick(
                    symbol=pick['symbol'],
                    direction=PickDirection.LONG if pick.get('direction', 'LONG').upper() == 'LONG' else PickDirection.SHORT,
                    entry_price=float(pick['entry']),
                    take_profit=float(pick['take_profit']),
                    stop_loss=float(pick['stop_loss']),
                    status=PickStatus.NEW,
                    notes=notes + [
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "note": market_context,
                            "model": "market-context"
                        },
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "note": f"WHY THIS STOCK WAS PICKED:\n{pick.get('note', pick.get('thesis', f'Verified by {verifier_model}'))}",
                            "model": verifier_model,
                            "verdict": pick.get("verdict"),
                            "technical": pick.get("technical"),
                            "fundamental": pick.get("fundamental"),
                            "catalyst": pick.get("catalyst"),
                            "risk": pick.get("risk"),
                            "action": pick.get("action")
                        }
                    ]
                )
                db.add(new_pick)
            except Exception as e:
                logger.error(f"Failed to save pick {pick}: {e}")
            await db.commit()
        await _set_config_value(db, _LAST_SUCCESS_KEY, today)
        logger.info(f"Loop 1 & 2 completed. Saved {len(verified_picks)} picks.")
        return "ok"


async def run_loop_3(late: bool = False) -> bool:
    """Execute Evaluator (5pm) pipeline. Returns True on commit. Raises on failure."""
    _, verifier_model = await get_dynamic_models()
    market_context = await _fetch_market_context()
    today = _today_ist_str()
    if late:
        market_context += (
            f"\n\nNOTE: This is a late catch-up evaluation for {today} (the scheduled "
            "5pm run was missed)."
        )
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AIPick).where(AIPick.status.in_([PickStatus.NEW, PickStatus.ACTED_ON]))
        )
        active_picks = result.scalars().all()

        if not active_picks:
            return True

        # Prepare pick wrappers to decouple DB objects from concurrent network tasks
        tasks = []
        sem = asyncio.Semaphore(3)
        
        async def evaluate_single(pick_id: int, pick_status: PickStatus, pick_created_at: datetime, p_data: dict):
            async with sem:
                try:
                    if pick_status == PickStatus.NEW:
                        # Calculate business days (Mon-Fri only) since pick creation.
                        # Picks are abandoned after 2+ fully elapsed business days (roughly 48h of market time).
                        business_days = _calculate_business_days_elapsed(pick_created_at)
                        if business_days >= 2:
                            return pick_id, {"action": "ABANDON", "note": f"Auto-abandoned after {business_days} fully elapsed business days with no action."}
                            
                    eval_data = await _call_evaluator(db, p_data, market_context)
                    return pick_id, eval_data
                except Exception as e:
                    logger.error(f"Failed to evaluate pick {pick_id}: {e}")
                    return pick_id, {"action": "HOLD", "note": f"Evaluation failed due to API error: {str(e)}"}

        for p in active_picks:
            p_data = {
                "symbol": p.symbol,
                "direction": p.direction.value,
                "entry": p.entry_price,
                "take_profit": p.take_profit,
                "stop_loss": p.stop_loss,
                "history": p.notes
            }
            tasks.append(evaluate_single(p.id, p.status, p.created_at, p_data))
            
        eval_results = await asyncio.gather(*tasks)
            
        # Sequentially apply results to DB objects
        pick_map = {p.id: p for p in active_picks}
        for pid, eval_data in eval_results:
            pick = pick_map[pid]
            notes = list(pick.notes)
            
            if eval_data.get("action") == "ABANDON":
                pick.status = PickStatus.ABANDONED
                pick.status_updated_at = datetime.now(timezone.utc)
                notes.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "note": eval_data.get("note", "Auto-abandoned due to 48h timeout with no action."),
                    "model": "system"
                })
            else:
                notes.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "note": market_context,
                    "model": "market-context"
                })
                notes.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "note": eval_data.get("note", "Re-evaluated."),
                    "model": verifier_model,
                    "verdict": eval_data.get("verdict"),
                    "technical": eval_data.get("technical"),
                    "fundamental": eval_data.get("fundamental"),
                    "catalyst": eval_data.get("catalyst"),
                    "risk": eval_data.get("risk"),
                    "action": eval_data.get("action")
                })
            pick.notes = notes

        await db.commit()
        await _set_config_value(db, _LAST_EVAL_KEY, _today_ist_str())
        logger.info(f"Loop 3 completed. Evaluated {len(active_picks)} active picks.")
        return True

async def _morning_catchup_due() -> bool:
    """Catch-up needed iff no successful morning run recorded today (IST)."""
    async with AsyncSessionLocal() as db:
        return _morning_due(await _get_config_value(db, _LAST_SUCCESS_KEY), _today_ist_str())


async def _evening_catchup_due() -> bool:
    """Catch-up needed iff past close, picks exist today, none evaluated today."""
    if not _past_market_hours():
        return False
    today = _today_ist_str()
    async with AsyncSessionLocal() as db:
        last_eval = await _get_config_value(db, _LAST_EVAL_KEY)
        if last_eval == today:
            return False
        return await _picks_created_today(db, today)


async def _eval_done_today() -> bool:
    async with AsyncSessionLocal() as db:
        return (await _get_config_value(db, _LAST_EVAL_KEY)) == _today_ist_str()


def _execute_morning_run(late: bool) -> None:
    """Run hunter+verifier once and report honestly (shared by catch-up + cron)."""
    from app.backgroundtasks._runtime import _run_async
    from app.jobs.runner import update_job_status_sync
    tag = " (catch-up, late)" if late else ""
    update_job_status_sync("job.ai_picks_morning", "running", progress=10,
                           message=f"Executing AI Hunter & Verifier...{tag}")
    try:
        outcome = _run_async(run_loop_1_and_2(late=late))
    except Exception as e:
        logger.exception(f"Error in Morning AI Picks: {e}")
        update_job_status_sync("job.ai_picks_morning", "failed", progress=0,
                               message="Failed", error=str(e)[:512])
        return
    now = datetime.now(timezone.utc)
    if outcome == "ok":
        update_job_status_sync("job.ai_picks_morning", "completed", progress=100,
                               message="Completed successfully" + (" (catch-up)" if late else ""),
                               last_completed=now)
        from app.jobs.runner import mark_job_success_sync
        mark_job_success_sync("job.ai_picks_morning")
    elif outcome == "empty":
        # Legitimate: no setups proposed or all rejected. Not a failure, but
        # the success date stays unwritten so the next boot scans afresh.
        update_job_status_sync("job.ai_picks_morning", "completed", progress=100,
                               message="No setups today", last_completed=now)
    else:  # "error:<detail>" — token/network/parse failure. Next boot retries.
        detail = outcome[6:] if outcome.startswith("error:") else outcome
        logger.error(f"Morning AI Picks failed: {detail}")
        update_job_status_sync("job.ai_picks_morning", "failed", progress=0,
                               message="Failed", error=detail[:512])


def _execute_evening_run(late: bool) -> None:
    """Run evaluator once and report honestly (shared by catch-up + cron)."""
    from app.backgroundtasks._runtime import _run_async
    from app.jobs.runner import update_job_status_sync
    tag = " (catch-up, late)" if late else ""
    update_job_status_sync("job.ai_picks_evening", "running", progress=10,
                           message=f"Executing AI Evaluator...{tag}")
    try:
        _run_async(run_loop_3(late=late))
    except Exception as e:
        logger.exception(f"Error in Evening AI Picks: {e}")
        update_job_status_sync("job.ai_picks_evening", "failed", progress=0,
                               message="Failed", error=str(e)[:512])
        return
    update_job_status_sync("job.ai_picks_evening", "completed", progress=100,
                           message="Completed successfully" + (" (catch-up)" if late else ""),
                           last_completed=datetime.now(timezone.utc))
    from app.jobs.runner import mark_job_success_sync
    mark_job_success_sync("job.ai_picks_evening")


def ai_picks_morning_worker() -> None:
    """Daemon thread for AI Picks Morning Hunter (cron: 0 8 * * *)."""
    from app.backgroundtasks._runtime import _run_async, _report_job_waiting, _sleep_interruptible, _shutdown_event, _is_job_enabled
    from app.workers.lifecycle import _startup_pipeline_done
    from app.jobs.runner import update_job_status_sync

    _startup_pipeline_done.wait()
    logger.info("AI Picks Morning daemon started.")

    # Boot catch-up (once): 8am run missed (app off / failed) and no success
    # recorded today → execute now, flagged late.
    try:
        if _is_job_enabled("job.ai_picks_morning") and _run_async(_morning_catchup_due()):
            logger.info("AI Picks Morning: missed run detected, catching up now (late).")
            _execute_morning_run(late=True)
    except Exception:
        logger.exception("AI Picks Morning: catch-up check failed")

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.ai_picks_morning"):
            update_job_status_sync("job.ai_picks_morning", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue

        wait_secs = _report_job_waiting("job.ai_picks_morning", "0 8 * * *")
        if _sleep_interruptible(wait_secs):
            break

        if not _shutdown_event.is_set():
            # Skip if already completed today (e.g. catch-up ran at 07:55) —
            # a second hunter run would duplicate picks.
            try:
                due = _run_async(_morning_catchup_due())
            except Exception:
                logger.exception("AI Picks Morning: pre-run check failed, running anyway")
                due = True
            if not due:
                logger.info("AI Picks Morning: already completed today, skipping scheduled run.")
                update_job_status_sync("job.ai_picks_morning", "completed", progress=100,
                                       message="Already completed today")
                continue
            _execute_morning_run(late=False)

    update_job_status_sync("job.ai_picks_morning", "idle", progress=0, message="Stopped")


def ai_picks_evening_worker() -> None:
    """Daemon thread for AI Picks Evening Evaluator (cron: 0 17 * * *)."""
    from app.backgroundtasks._runtime import _run_async, _report_job_waiting, _sleep_interruptible, _shutdown_event, _is_job_enabled
    from app.workers.lifecycle import _startup_pipeline_done
    from app.jobs.runner import update_job_status_sync

    _startup_pipeline_done.wait()
    logger.info("AI Picks Evening daemon started.")

    # Boot catch-up (once): past close with unevaluated picks from today and
    # no evaluation recorded → evaluate now, flagged late. If the app was off
    # all day there are no picks (or the morning runner covers it) → skip.
    try:
        if _is_job_enabled("job.ai_picks_evening") and _run_async(_evening_catchup_due()):
            logger.info("AI Picks Evening: unevaluated picks found past close, catching up now (late).")
            _execute_evening_run(late=True)
    except Exception:
        logger.exception("AI Picks Evening: catch-up check failed")

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.ai_picks_evening"):
            update_job_status_sync("job.ai_picks_evening", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue

        wait_secs = _report_job_waiting("job.ai_picks_evening", "0 17 * * *")
        if _sleep_interruptible(wait_secs):
            break

        if not _shutdown_event.is_set():
            # Skip if already evaluated today (e.g. afternoon catch-up ran).
            try:
                done = _run_async(_eval_done_today())
            except Exception:
                logger.exception("AI Picks Evening: pre-run check failed, running anyway")
                done = False
            if done:
                logger.info("AI Picks Evening: already evaluated today, skipping scheduled run.")
                update_job_status_sync("job.ai_picks_evening", "completed", progress=100,
                                       message="Already evaluated today")
                continue
            _execute_evening_run(late=False)

    update_job_status_sync("job.ai_picks_evening", "idle", progress=0, message="Stopped")