import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ai_picks import AIPick, PickStatus, PickDirection, AIPickTrace
import time
from app.workers.lifecycle import _startup_pipeline_done
from app.services.llm_provider import stream_chat_completion
from app.services.ai_chat_service import BLM_TOOLS, BLM_TOOLS_ANTHROPIC, _run_tools_parallel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zen API resilience (Phase 1: timeout + retry)
# ---------------------------------------------------------------------------
# Deep-research loops (Hunter/Verifier/Evaluator) call 6-8 tools in parallel
# per turn and then generate up to 4k tokens of reasoning. With the previous
# 120s timeout the 7th-3rd API call would routinely exceed the deadline and
# fail the entire pipeline. We now use a configurable, longer timeout and
# retry transient timeouts before giving up.
async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    caller: str,
    **kwargs: Any,
) -> httpx.Response:
    """POST to the Zen API with retry on transient timeouts.

    - Forces ``timeout=zen_api_timeout_seconds`` (overrides any caller value).
    - Retries ``httpx.ReadTimeout`` and ``httpx.ConnectTimeout`` up to
      ``zen_api_max_retries`` times, sleeping ``zen_api_retry_backoff_seconds``
      between attempts.
    - Other ``httpx.HTTPError`` subclasses (connect refused, 5xx after
      ``raise_for_status``) bubble up immediately — only *timeout* is
      considered transient here, matching the failure mode in the incident
      report (June 22 — both runs failed on ``httpx.ReadTimeout``).
    """
    timeout = settings.zen_api_timeout_seconds
    max_retries = max(0, settings.zen_api_max_retries)
    backoff = max(0.0, settings.zen_api_retry_backoff_seconds)

    # Caller might have passed timeout=...; always override to the configured value.
    kwargs.pop("timeout", None)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await client.post(url, timeout=timeout, **kwargs)
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_exc = exc
            if attempt >= max_retries:
                logger.error(
                    "Zen API call from %s exhausted %d retries (last error: %s)",
                    caller, max_retries, exc,
                )
                raise
            logger.warning(
                "Zen API call from %s timed out (attempt %d/%d): %s — retrying in %.1fs",
                caller, attempt + 1, max_retries + 1, exc, backoff,
            )
            if backoff > 0:
                await asyncio.sleep(backoff)
    # Defensive — the loop above always either returns or raises.
    assert last_exc is not None
    raise last_exc

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
3. CATALYST VALIDATION: For top candidates, call `get_company_news` and `get_upcoming_events` to confirm positive catalysts and avoid adverse events.
4. SYNTHESIS: Select the absolute best 4-6 setups. Discard weak setups.
</task>

<tool_usage_guidelines>
- Use `get_global_notifications` for real-time alerts and `get_volume_gainers` for volume surges.
- If `get_company_news` fails or returns insufficient data, immediately fallback to `company_fdm` to check recent corporate announcements.
- Do not guess parameter values (e.g., sector slugs). If you need an industry list, call `list_industries` first.
</tool_usage_guidelines>

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
2. Call tools like `get_symbol_data`, `company_fdm`, and `get_company_news` to check for red flags.
3. REJECT any setup that has poor financials, bad news sentiment, or overextended technicals.
4. Keep only the absolute best 2 to 3 setups. If none pass your strict criteria, return an empty array.
</task>

<tool_usage_guidelines>
- If `get_company_news` fails or returns insufficient data, immediately fallback to `company_fdm` to check recent corporate announcements.
</tool_usage_guidelines>

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
   - Use your tools to check today's closing price, recent news, and technicals for the given symbol.
   - Assess if the thesis remains intact, targets need adjustment, or position must close.
   - Compare current price action to the entry point and stop loss level.

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



async def _run_antigravity_worker_loop(messages: list[dict], model: str, system_prompt: str | None = None) -> str:
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

async def _call_kimi_hunter(client: httpx.AsyncClient, db: AsyncSession, market_context: str = "") -> list[dict]:
    """Loop 1: Run hunt for picks."""
    logger.info("Loop 1: Hunter starting")
    start_time = time.time()
    
    if settings.ai_provider == "antigravity":
        sys_prompt = HUNTER_PROMPT + "\n\n" + market_context
        messages = [{"role": "user", "content": "Execute your market scan and provide the top 2-3 swing trade picks."}]
        text = await _run_antigravity_worker_loop(
            messages=messages,
            model="gemini-3.1-pro-high",
            system_prompt=sys_prompt
        )
        duration = int((time.time() - start_time) * 1000)
        full_prompt = sys_prompt + "\n\n" + json.dumps(messages)
        await _save_trace(db, "MULTI", "HUNTER", full_prompt, text, duration, "SUCCESS")
        try:
            return _extract_json_block(text, "picks")
        except Exception as e:
            logger.error(f"Hunter parsing failed: {e}. Raw content: {text}")
        return []

    messages = [{"role": "system", "content": HUNTER_PROMPT + "\n\n" + market_context}]
    messages.append({"role": "user", "content": "Execute your market scan and provide the top 2-3 swing trade picks."})
    
    for turn_idx in range(60):
        resp = await _post_with_retry(
            client,
            f"{settings.zen_base_url}/chat/completions",
            caller=f"hunter:turn{turn_idx}",
            headers={"Authorization": f"Bearer {settings.opencode_zen_api_key}"},
            json={
                "model": "kimi-k2.6",
                "messages": messages,
                "tools": BLM_TOOLS,
                "temperature": 0.2
            },
        )
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
        messages.append(message)

        if message.get("tool_calls"):
            tool_calls = message["tool_calls"]
            logger.info(f"Hunter using tools: {[tc['function']['name'] for tc in tool_calls]}")
            normalised = [
                {"id": tc["id"], "name": tc["function"]["name"], "args": json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}}
                for tc in tool_calls
            ]
            _, tool_msgs = await _run_tools_parallel(normalised, set())
            for tm in tool_msgs:
                messages.append({"role": "tool", "tool_call_id": tm["id"], "content": tm["content"]})

            if turn_idx == 45:
                messages.append({
                    "role": "user",
                    "content": "WARNING: You have used 45 turns. The strict limit is 60. Please finalize your analysis and output your final <picks> block soon."
                })
        else:
            break
            
    content = messages[-1].get("content", "")
    start_time = time.time()

    duration = int((time.time() - start_time) * 1000)
    prompt_str = json.dumps(messages[:-1])
    response_str = messages[-1].get("content", "") if messages else ""
    await _save_trace(db, "MULTI", "HUNTER", prompt_str, response_str, duration, "SUCCESS")
    try:
        return _extract_json_block(content, "picks")
    except Exception as e:
        logger.error(f"Hunter parsing failed: {e}. Raw content: {content}")
    return []

async def _call_minimax_verifier(client: httpx.AsyncClient, db: AsyncSession, proposed_picks: list[dict], market_context: str = "") -> list[dict]:
    """Loop 2: Run verify picks."""
    logger.info("Loop 2: Verifier starting")
    start_time = time.time()
    
    if settings.ai_provider == "antigravity":
        sys_prompt = VERIFIER_PROMPT + "\n\n" + market_context
        user_msg = f"Here are the proposed setups. Verify them carefully:\n{json.dumps(proposed_picks, indent=2)}"
        messages = [{"role": "user", "content": user_msg}]
        text = await _run_antigravity_worker_loop(
            messages=messages,
            model="gemini-3.7-flash-medium",
            system_prompt=sys_prompt
        )
        duration = int((time.time() - start_time) * 1000)
        full_prompt = sys_prompt + "\n\n" + json.dumps(messages)
        await _save_trace(db, "MULTI", "VERIFIER", full_prompt, text, duration, "SUCCESS")
        try:
            return _extract_json_block(text, "verified_picks")
        except Exception as e:
            logger.error(f"Verifier parsing failed: {e}. Raw content: {text}")
        return []

    messages = [
        {"role": "user", "content": f"Here are the proposed setups. Verify them carefully:\n{json.dumps(proposed_picks, indent=2)}"}
    ]
    
    for turn_idx in range(60):
        resp = await _post_with_retry(
            client,
            f"{settings.zen_base_url}/messages",
            caller=f"verifier:turn{turn_idx}",
            headers={
                "x-api-key": settings.opencode_zen_api_key,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "minimax-m2.5",
                "system": VERIFIER_PROMPT + "\n\n" + market_context,
                "messages": messages,
                "tools": BLM_TOOLS_ANTHROPIC,
                "max_tokens": 4096,
                "temperature": 0.1
            },
        )
        resp.raise_for_status()
        data = resp.json()

        assistant_msg = {"role": "assistant", "content": data["content"]}
        messages.append(assistant_msg)

        tool_uses = [c for c in data["content"] if c["type"] == "tool_use"]
        if tool_uses:
            logger.info(f"Verifier using tools: {[tu['name'] for tu in tool_uses]}")
            normalised = [
                {"id": tu["id"], "name": tu["name"], "args": tu["input"]}
                for tu in tool_uses
            ]
            _, tool_msgs = await _run_tools_parallel(normalised, set())

            anthropic_results = []
            for tm in tool_msgs:
                anthropic_results.append({
                    "type": "tool_result",
                    "tool_use_id": tm["id"],
                    "content": [{"type": "text", "text": tm["content"]}]
                })

            if turn_idx == 45:
                anthropic_results.append({
                    "type": "text",
                    "text": "WARNING: You have used 45 turns. The strict limit is 60. Please finalize your analysis and output your final XML block soon."
                })

            messages.append({"role": "user", "content": anthropic_results})
        else:
            break

    content = ""
    for c in messages[-1].get("content", []):
        if c["type"] == "text":
            content += c["text"]

    duration = int((time.time() - start_time) * 1000)
    prompt_str = json.dumps(messages[:-1])
    response_str = content
    await _save_trace(db, "MULTI", "VERIFIER", prompt_str, response_str, duration, "SUCCESS")
    try:
        return _extract_json_block(content, "verified_picks")
    except Exception as e:
        logger.error(f"Verifier parsing failed: {e}. Raw content: {content}")
    return []

async def _call_minimax_evaluator(client: httpx.AsyncClient, db: AsyncSession, pick_data: dict, market_context: str = "") -> dict:
    """Loop 3: Run MiniMax 2.5 to evaluate an existing pick."""
    start_time = time.time()
    if settings.ai_provider == "antigravity":
        sys_prompt = EVALUATOR_PROMPT + "\n\n" + market_context
        user_msg = f"Re-evaluate this active position:\n{json.dumps(pick_data, indent=2)}"
        messages = [{"role": "user", "content": user_msg}]
        text = await _run_antigravity_worker_loop(
            messages=messages,
            model="gemini-3.7-flash-medium",
            system_prompt=sys_prompt
        )
        duration = int((time.time() - start_time) * 1000)
        full_prompt = sys_prompt + "\n\n" + json.dumps(messages)
        await _save_trace(db, pick_data.get("symbol", "UNKNOWN"), "EVALUATOR", full_prompt, text, duration, "SUCCESS")
        try:
            return _extract_json_block(text, "evaluation")
        except Exception as e:
            logger.error(f"Evaluator parsing failed: {e}. Raw content: {text}")
        return {}

    messages = [
        {"role": "user", "content": f"Re-evaluate this active position:\n{json.dumps(pick_data, indent=2)}"}
    ]
    
    for turn_idx in range(60):
        resp = await _post_with_retry(
            client,
            f"{settings.zen_base_url}/messages",
            caller=f"evaluator:turn{turn_idx}",
            headers={
                "x-api-key": settings.opencode_zen_api_key,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "minimax-m2.5",
                "system": EVALUATOR_PROMPT + "\n\n" + market_context,
                "messages": messages,
                "tools": BLM_TOOLS_ANTHROPIC,
                "max_tokens": 4096,
                "temperature": 0.1
            },
        )
        resp.raise_for_status()
        data = resp.json()
        
        assistant_msg = {"role": "assistant", "content": data["content"]}
        messages.append(assistant_msg)
        
        tool_uses = [c for c in data["content"] if c["type"] == "tool_use"]
        if tool_uses:
            normalised = [
                {"id": tu["id"], "name": tu["name"], "args": tu["input"]}
                for tu in tool_uses
            ]
            _, tool_msgs = await _run_tools_parallel(normalised, set())
            
            anthropic_results = []
            for tm in tool_msgs:
                anthropic_results.append({
                    "type": "tool_result",
                    "tool_use_id": tm["id"],
                    "content": [{"type": "text", "text": tm["content"]}]
                })
                
            if turn_idx == 45:
                anthropic_results.append({
                    "type": "text",
                    "text": "WARNING: You have used 45 turns. The strict limit is 60. Please finalize your analysis and output your final XML block soon."
                })
                
            messages.append({"role": "user", "content": anthropic_results})
        else:
            break
            
    content = ""
    for c in messages[-1].get("content", []):
        if c["type"] == "text":
            content += c["text"]
            
    duration = int((time.time() - start_time) * 1000)
    prompt_str = json.dumps(messages[:-1])
    response_str = content
    await _save_trace(db, pick_data.get("symbol", "UNKNOWN"), "EVALUATOR", prompt_str, response_str, duration, "SUCCESS")
    try:
        return _extract_json_block(content, "evaluation")
    except Exception as e:
        logger.error(f"Evaluator parsing failed: {e}. Raw content: {content}")
    
    return {"note": "Failed to generate evaluation.", "action": "HOLD"}



from app.mcp_server import get_top_gainers, get_top_losers, get_volume_gainers, get_global_news

async def _fetch_market_context() -> str:
    """Fetch a high-level summary of the broader market conditions."""
    context_parts = ["### GLOBAL MARKET CONTEXT ###"]
    
    # 1. Top Gainers & Losers
    try:
        gainers = await get_top_gainers(category="allSec")
        losers = await get_top_losers(category="allSec")
        
        g_symbols = [g.get('symbol', '') for g in gainers[:5]]
        l_symbols = [l.get('symbol', '') for l in losers[:5]]
        
        context_parts.append(f"Top Gainers: {', '.join(g_symbols)}")
        context_parts.append(f"Top Losers: {', '.join(l_symbols)}")
    except Exception as e:
        logger.error(f"Failed to fetch market gainers/losers: {e}")
        
    # 2. Volume Surge
    try:
        vol = await get_volume_gainers()
        v_symbols = [v.get('symbol', '') for v in vol.get('data', [])[:5]]
        context_parts.append(f"Volume Surges: {', '.join(v_symbols)}")
    except Exception as e:
        logger.error(f"Failed to fetch volume gainers: {e}")
        
    # 3. Global News
    try:
        news = await get_global_news(limit=5)
        articles = news.get("articles", [])
        news_lines = []
        for a in articles:
            title = a.get("title", "")
            sentiment = a.get("sentiment_label", "NEUTRAL")
            news_lines.append(f"- [{sentiment}] {title}")
        if news_lines:
            context_parts.append("Latest Global News:\n" + "\n".join(news_lines))
    except Exception as e:
        logger.error(f"Failed to fetch global news: {e}")
        
    return "\n\n".join(context_parts)


async def run_loop_1_and_2():
    """Execute Hunter (8am) and Verifier pipelines."""
    market_context = await _fetch_market_context()
    
    async with AsyncSessionLocal() as db:
        async with httpx.AsyncClient() as client:
            proposed_picks = await _call_kimi_hunter(client, db, market_context)
            if not proposed_picks:
                logger.info("Loop 1 found no valid setups today.")
                return
                
            verified_picks = await _call_minimax_verifier(client, db, proposed_picks, market_context)
            if not verified_picks:
                logger.info("Loop 2 rejected all setups.")
                return
                
            # Commit to DB
            for pick in verified_picks:
                try:
                    new_pick = AIPick(
                        symbol=pick['symbol'],
                        direction=PickDirection.LONG if pick.get('direction', 'LONG').upper() == 'LONG' else PickDirection.SHORT,
                        entry_price=float(pick['entry']),
                        take_profit=float(pick['take_profit']),
                        stop_loss=float(pick['stop_loss']),
                        status=PickStatus.NEW,
                        notes=[
                            {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "note": market_context,
                                "model": "market-context"
                            },
                            {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "note": f"WHY THIS STOCK WAS PICKED:\n{pick.get('note', pick.get('thesis', 'Verified by MiniMax 2.5'))}",
                                "model": "minimax-m2.5",
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
            logger.info(f"Loop 1 & 2 completed. Saved {len(verified_picks)} picks.")


async def run_loop_3():
    """Execute Evaluator (5pm) pipeline."""
    market_context = await _fetch_market_context()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AIPick).where(AIPick.status.in_([PickStatus.NEW, PickStatus.ACTED_ON]))
        )
        active_picks = result.scalars().all()
        
        if not active_picks:
            return

        # Prepare pick wrappers to decouple DB objects from concurrent network tasks
        tasks = []
        async with httpx.AsyncClient() as client:
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
                                
                        eval_data = await _call_minimax_evaluator(client, db, p_data, market_context)
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
                    "model": "minimax-m2.5",
                    "verdict": eval_data.get("verdict"),
                    "technical": eval_data.get("technical"),
                    "fundamental": eval_data.get("fundamental"),
                    "catalyst": eval_data.get("catalyst"),
                    "risk": eval_data.get("risk"),
                    "action": eval_data.get("action")
                })
            pick.notes = notes
            
        await db.commit()
        logger.info(f"Loop 3 completed. Evaluated {len(active_picks)} active picks.")

def ai_picks_morning_worker() -> None:
    """Daemon thread for AI Picks Morning Hunter (cron: 0 8 * * *)."""
    from app.backgroundtasks._runtime import _run_async, _report_job_waiting, _sleep_interruptible, _shutdown_event, _is_job_enabled
    from app.workers.lifecycle import _startup_pipeline_done
    from app.jobs.runner import update_job_status_sync
    
    _startup_pipeline_done.wait()
    logger.info("AI Picks Morning daemon started.")
    
    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.ai_picks_morning"):
            update_job_status_sync("job.ai_picks_morning", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
            
        wait_secs = _report_job_waiting("job.ai_picks_morning", "0 8 * * *")
        if _sleep_interruptible(wait_secs):
            break
            
        if not _shutdown_event.is_set():
            update_job_status_sync("job.ai_picks_morning", "running", progress=10, message="Executing Kimi Hunter & Verifier...")
            try:
                _run_async(run_loop_1_and_2())
                update_job_status_sync("job.ai_picks_morning", "completed", progress=100, message="Completed successfully")
            except Exception as e:
                logger.exception(f"Error in Morning AI Picks: {e}")
                update_job_status_sync("job.ai_picks_morning", "idle", progress=0, message="Failed")
                
    update_job_status_sync("job.ai_picks_morning", "idle", progress=0, message="Stopped")

def ai_picks_evening_worker() -> None:
    """Daemon thread for AI Picks Evening Evaluator (cron: 0 17 * * *)."""
    from app.backgroundtasks._runtime import _run_async, _report_job_waiting, _sleep_interruptible, _shutdown_event, _is_job_enabled
    from app.workers.lifecycle import _startup_pipeline_done
    from app.jobs.runner import update_job_status_sync
    
    _startup_pipeline_done.wait()
    logger.info("AI Picks Evening daemon started.")
    
    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.ai_picks_evening"):
            update_job_status_sync("job.ai_picks_evening", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
            
        wait_secs = _report_job_waiting("job.ai_picks_evening", "0 17 * * *")
        if _sleep_interruptible(wait_secs):
            break
            
        if not _shutdown_event.is_set():
            update_job_status_sync("job.ai_picks_evening", "running", progress=10, message="Executing AI Evaluator...")
            try:
                _run_async(run_loop_3())
                update_job_status_sync("job.ai_picks_evening", "completed", progress=100, message="Completed successfully")
            except Exception as e:
                logger.exception(f"Error in Evening AI Picks: {e}")
                update_job_status_sync("job.ai_picks_evening", "idle", progress=0, message="Failed")
                
    update_job_status_sync("job.ai_picks_evening", "idle", progress=0, message="Stopped")