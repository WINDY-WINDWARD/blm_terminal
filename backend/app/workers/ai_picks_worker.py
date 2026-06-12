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
from app.models.ai_picks import AIPick, PickStatus, PickDirection
from app.workers.lifecycle import _startup_pipeline_done
from app.services.ai_chat_service import BLM_TOOLS, BLM_TOOLS_ANTHROPIC, _run_tools_parallel

logger = logging.getLogger(__name__)

# Bullet-proof System Prompts
HUNTER_PROMPT = """You are 'The Hunter', an elite, aggressive quantitative analyst AI.
Your objective: Scan the Indian Stock Market (NSE) to identify 2-3 high-probability short-term swing trade setups.
You have access to tools that provide top gainers, screener data, news, fair value, and announcements.

INSTRUCTIONS:
1. Use `get_top_gainers` and `get_volume_gainers` to find active symbols.
2. Use `run_tql_screener` with strong momentum conditions if needed.
3. Once you identify candidates, use `screener_company` and `get_upcoming_events` to check fundamentals and catalysts.
4. Filter out any stock with poor fundamentals or immediate adverse events.
5. You MUST output your final picks strictly as a JSON array of objects inside a <picks> XML tag.

OUTPUT FORMAT:
<picks>
[
  {
    "symbol": "TICKER",
    "direction": "LONG",
    "entry": 100.50,
    "take_profit": 110.00,
    "stop_loss": 95.00,
    "thesis": "Strong volume breakout aligned with positive sector news and upcoming earnings catalyst."
  }
]
</picks>

Do not include markdown outside the tags or conversational filler. Only the <picks> block.
"""

VERIFIER_PROMPT = """You are 'The Verifier', a strict Chief Risk Officer AI.
Your objective: Evaluate a list of proposed swing trade setups and REJECT weak ones.
You have access to tools to independently verify the setups (technicals, fundamentals, news, fair value).

INSTRUCTIONS:
1. I will provide a JSON list of proposed setups.
2. For each setup, use your tools (`get_company_news`, `screener_company`, `get_upcoming_events`) to independently verify the thesis.
3. Reject any setup that has red flags (bad news, overvalued, poor technical structure).
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
    "thesis": "Verified: Solid fundamentals, no immediate bad news. Adjusted TP for better R:R."
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
  "note": "Price hit strong resistance at 105. Suggest tightening stop loss to 102 to protect profits.",
  "action": "HOLD" // or "CLOSE"
}
</evaluation>
"""

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


async def _call_kimi_hunter(client: httpx.AsyncClient) -> list[dict]:
    """Loop 1: Run Kimi 2.6 to hunt for picks."""
    logger.info("Loop 1: Kimi Hunter starting")
    
    messages = [{"role": "system", "content": HUNTER_PROMPT}]
    messages.append({"role": "user", "content": "Execute your market scan and provide the top 2-3 swing trade picks."})
    
    for _ in range(3):
        resp = await client.post(
            f"{settings.zen_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.opencode_zen_api_key}"},
            json={
                "model": "kimi-k2.6",
                "messages": messages,
                "tools": BLM_TOOLS,
                "temperature": 0.2
            },
            timeout=120.0
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
        else:
            break
            
    content = messages[-1].get("content", "")
    try:
        return _extract_json_block(content, "picks")
    except Exception as e:
        logger.error(f"Hunter parsing failed: {e}. Raw content: {content}")
    return []

async def _call_minimax_verifier(client: httpx.AsyncClient, proposed_picks: list[dict]) -> list[dict]:
    """Loop 2: Run MiniMax 2.5 to verify picks."""
    logger.info("Loop 2: MiniMax Verifier starting")
    
    messages = [
        {"role": "user", "content": f"Here are the proposed setups. Verify them carefully:\n{json.dumps(proposed_picks, indent=2)}"}
    ]
    
    for _ in range(3):
        resp = await client.post(
            f"{settings.zen_base_url}/messages",
            headers={
                "x-api-key": settings.opencode_zen_api_key,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "minimax-m2.5",
                "system": VERIFIER_PROMPT,
                "messages": messages,
                "tools": BLM_TOOLS_ANTHROPIC,
                "max_tokens": 4096,
                "temperature": 0.1
            },
            timeout=120.0
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
            messages.append({"role": "user", "content": anthropic_results})
        else:
            break
            
    content = ""
    for c in messages[-1].get("content", []):
        if c["type"] == "text":
            content += c["text"]
            
    try:
        return _extract_json_block(content, "verified_picks")
    except Exception as e:
        logger.error(f"Verifier parsing failed: {e}. Raw content: {content}")
    return []

async def _call_minimax_evaluator(client: httpx.AsyncClient, pick_data: dict) -> dict:
    """Loop 3: Run MiniMax 2.5 to evaluate an existing pick."""
    messages = [
        {"role": "user", "content": f"Re-evaluate this active position:\n{json.dumps(pick_data, indent=2)}"}
    ]
    
    for _ in range(3):
        resp = await client.post(
            f"{settings.zen_base_url}/messages",
            headers={
                "x-api-key": settings.opencode_zen_api_key,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "minimax-m2.5",
                "system": EVALUATOR_PROMPT,
                "messages": messages,
                "tools": BLM_TOOLS_ANTHROPIC,
                "max_tokens": 4096,
                "temperature": 0.1
            },
            timeout=120.0
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
            messages.append({"role": "user", "content": anthropic_results})
        else:
            break
            
    content = ""
    for c in messages[-1].get("content", []):
        if c["type"] == "text":
            content += c["text"]
            
    try:
        return _extract_json_block(content, "evaluation")
    except Exception as e:
        logger.error(f"Evaluator parsing failed: {e}. Raw content: {content}")
    
    return {"note": "Failed to generate evaluation.", "action": "HOLD"}


async def run_loop_1_and_2():
    """Execute Hunter (8am) and Verifier pipelines."""
    async with httpx.AsyncClient() as client:
        proposed_picks = await _call_kimi_hunter(client)
        if not proposed_picks:
            logger.info("Loop 1 found no valid setups today.")
            return
            
        verified_picks = await _call_minimax_verifier(client, proposed_picks)
        if not verified_picks:
            logger.info("Loop 2 rejected all setups.")
            return
            
        # Commit to DB
        async with AsyncSessionLocal() as db:
            for pick in verified_picks:
                try:
                    new_pick = AIPick(
                        symbol=pick['symbol'],
                        direction=PickDirection.LONG if pick.get('direction', 'LONG').upper() == 'LONG' else PickDirection.SHORT,
                        entry_price=float(pick['entry']),
                        take_profit=float(pick['take_profit']),
                        stop_loss=float(pick['stop_loss']),
                        status=PickStatus.NEW,
                        notes=[{
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "note": pick.get('thesis', 'Verified by MiniMax 2.5'),
                            "model": "minimax-m2.5"
                        }]
                    )
                    db.add(new_pick)
                except Exception as e:
                    logger.error(f"Failed to save pick {pick}: {e}")
            await db.commit()
            logger.info(f"Loop 1 & 2 completed. Saved {len(verified_picks)} picks.")

async def run_loop_3():
    """Execute Evaluator (5pm) pipeline."""
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
                                
                        eval_data = await _call_minimax_evaluator(client, p_data)
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
                    "note": eval_data.get("note", "Re-evaluated."),
                    "model": "minimax-m2.5"
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