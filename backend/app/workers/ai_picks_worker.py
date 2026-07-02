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
HUNTER_PROMPT = """You are 'The Hunter', an elite, quantitative equity research AI specializing in actionable mid-cap swing trades.
Your objective: Execute a deep search across the NSE to identify 4-6 highly actionable, high-probability mid-cap swing trade setups.

INSTRUCTIONS:
1. DEEP SEARCH START: First, use `get_global_notifications` and `get_volume_gainers` to identify stocks that have recently triggered technical breakouts or abnormal volume.
2. TECHNICAL SCREENING: Use `run_tql_screener` to find growth stocks with bullish momentum (e.g., RSI > 55, MACDHist > 0, From52wHigh > -15). Focus on mid-cap setups.
3. CATALYST & FUNDAMENTAL CHECK: For your top candidates, deeply analyze them using `get_company_news` and `get_upcoming_events`.
4. RIGOROUS FILTERING: Discard any stock with imminent adverse events, poor relative strength, or weak news sentiment. Ensure you return exactly 4 to 6 high-conviction, actionable setups.
5. DETAILED THESIS: Your thesis for each pick MUST be extremely detailed. Break down the technical setup considered, the specific news catalysts evaluated, and upcoming events.
6. OUTPUT: You MUST output your final 4-6 picks strictly as a JSON array inside a <picks> XML tag.

OUTPUT FORMAT:
<picks>
[
  {
    "symbol": "TICKER",
    "direction": "LONG",
    "entry": 100.50,
    "take_profit": 110.00,
    "stop_loss": 95.00,
    "thesis": "[Details Considered] Technicals: RSI at 60, MACD crossover confirmed. Scan/Notifs: Triggered volume breakout alert today. Catalyst: Positive sentiment from recent contract win news. Events: No major earnings risk in the next 14 days."
  }
]
</picks>

Do not include markdown outside the tags or conversational filler. Only the <picks> block.
"""

VERIFIER_PROMPT = """You are 'The Verifier', a strict Chief Risk Officer AI.
Your objective: Evaluate a list of 4-6 proposed mid-cap swing trade setups and independently verify them.
You have access to tools to independently verify the setups (technicals, fundamentals, news, fair value).

INSTRUCTIONS:
1. I will provide a JSON list of proposed setups.
2. For each setup, use your tools (`get_company_news`, `company_fdm`, `get_upcoming_events`) to independently verify the detailed thesis provided.
3. Reject ONLY setups that have clear red flags (imminent bad news, extremely overvalued, or poor technical structure). Preserve strong mid-cap growth setups.
4. Refine the entry, take_profit, and stop_loss levels to be mathematically sound (e.g., RR > 2:1).
5. Output the surviving, verified picks strictly as a JSON array inside a <verified_picks> XML tag.

OUTPUT FORMAT:
<verified_picks>
[
  {
    "symbol": "TICKER",
    "direction": "LONG",
    "entry": 100.50,
    "take_profit": 115.00,
    "stop_loss": 96.00,
    "note": "Verified: Solid fundamentals. Adjusted TP for better R:R.",
    "verdict": "BULLISH",
    "technical": "RSI solid.",
    "fundamental": "No immediate bad news.",
    "catalyst": "Earnings upcoming.",
    "risk": "Market weakness.",
    "action": "BUY"
  }
]
</verified_picks>
"""

EVALUATOR_PROMPT = """You are 'The Evaluator', a portfolio management AI.
Your objective: Re-evaluate active swing trade positions based on today's price action and news.
You will be given the current state of a pick. 

INSTRUCTIONS:
1. Use your tools to check today's closing price, recent news, and technicals for the given symbol.
2. Evaluate if the thesis is still intact, if targets should be adjusted, or if the position should be closed.
3. Output your evaluation strictly as a JSON object inside an <evaluation> XML tag.

OUTPUT FORMAT:
<evaluation>
{
  "note": "Price hit strong resistance at 105. Suggest tightening stop loss.",
  "verdict": "NEUTRAL",
  "technical": "Resistance at 105.",
  "fundamental": "No change.",
  "catalyst": "None.",
  "risk": "High if market drops.",
  "action": "HOLD" // or "CLOSE"
}
</evaluation>
"""


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
    if f"<{tag}>" in content:
        content = content.split(f"<{tag}>")[1].split(f"</{tag}>")[0].strip()
    
    # Use regex to find the innermost JSON if it's wrapped in markdown
    match = re.search(r"```(?:json)?\n?(.*?)\n?```", content, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        json_str = content.strip()
        
    return json.loads(json_str)


async def _call_kimi_hunter(client: httpx.AsyncClient, db: AsyncSession, market_context: str = "") -> list[dict]:
    """Loop 1: Run Kimi 2.6 to hunt for picks."""
    logger.info("Loop 1: Kimi Hunter starting")
    start_time = time.time()
    
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
    """Loop 2: Run MiniMax 2.5 to verify picks."""
    logger.info("Loop 2: MiniMax Verifier starting")
    start_time = time.time()
    
    start_time = time.time()
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

    start_time = time.time()

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
            
    start_time = time.time()

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
        v_symbols = [v.get('symbol', '') for v in vol[:5]]
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
                            age = datetime.now(timezone.utc) - pick_created_at.replace(tzinfo=timezone.utc)
                            if age > timedelta(hours=48):
                                return pick_id, {"action": "ABANDON", "note": "Auto-abandoned due to 48h timeout with no action."}
                                
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