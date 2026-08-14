"""
Standalone script to trigger run_loop_1_and_2() (Hunter + Verifier loops) with live verbose logging.
Run from backend/ directory with the venv active:
  python scripts/trigger_picks.py
"""
import asyncio
import logging
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up logging for the script
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("trigger_picks")
# Suppress some noisy external logs
logging.getLogger("httpx").setLevel(logging.WARNING)

async def _verbose_loop(messages: list[dict], model: str, system_prompt: str | None = None) -> str:
    """A verbose version of _run_antigravity_worker_loop that prints real-time events."""
    from app.services.llm_provider import stream_chat_completion
    from app.services.ai_chat_service import BLM_TOOLS, _run_tools_parallel
    
    logger.info(f"\nMODEL: {model}")
    if system_prompt:
        logger.info(f"SYSTEM PROMPT (first 300): {system_prompt[:300]}")
    for m in messages:
        logger.info(f"USER: {m['content']}")
    logger.info("=" * 70)

    seen_calls = set()
    async def executor(tool_calls: list[dict]) -> tuple[list[str], list[dict]]:
        for tc in tool_calls:
            logger.info(f"\n>>> TOOL CALL #{len(seen_calls) + 1}: {tc['name']}({tc['args']})")
        
        events, tool_msgs = await _run_tools_parallel(tool_calls, seen_calls)
        
        for tm in tool_msgs:
            tname = next((tc["name"] for tc in tool_calls if tc["id"] == tm["id"]), "unknown")
            snippet = tm["content"][:200].replace('\n', ' ')
            logger.info(f"<<< TOOL RESULT: {tname} — {snippet}...")
            
        return events, tool_msgs

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
            # Print token by token to console without newline
            sys.stdout.write(evt["text"])
            sys.stdout.flush()
        elif evt["type"] == "error":
            logger.error(f"\n!!! ERROR: {evt['message']}")
            raise RuntimeError(f"API error: {evt['message']}")
            
    print("\n" + "=" * 70)
    return full_content

async def run(mode="all"):
    # Monkey-patch the worker loop temporarily so we can inject our verbose loop
    import app.workers.ai_picks_worker as worker
    worker._run_antigravity_worker_loop = _verbose_loop
    worker._run_openai_worker_loop = _verbose_loop
    
    from app.database import AsyncSessionLocal
    import httpx
    
    logger.info(f"Triggering {mode} via trigger_picks...")
    
    async with httpx.AsyncClient(timeout=120) as client:
        async with AsyncSessionLocal() as db:
            if mode in ("all", "hunter"):
                logger.info("Running Hunter...")
                picks = await worker._call_kimi_hunter(client, db)
                logger.info(f"Hunter returned {len(picks)} proposed picks.")
            else:
                picks = []
                
            if mode in ("all", "verifier"):
                if not picks and mode == "verifier":
                    # Provide dummy data for isolated verifier testing
                    picks = [{"symbol": "RELIANCE", "direction": "LONG", "entry": 3000, "take_profit": 3200, "stop_loss": 2900, "thesis": "Testing."}]
                logger.info("Running Verifier...")
                verified = await worker._call_minimax_verifier(client, db, picks)
                logger.info(f"Verifier approved {len(verified)} picks.")
                for p in verified:
                    logger.info(f"  -> {p['symbol']}: {p.get('action', 'N/A')}")
                    
            if mode == "evaluator":
                logger.info("Running Evaluator on dummy position...")
                dummy_pos = {"symbol": "RELIANCE", "buy_price": 2800, "current_price": 2900, "unrealized_pnl": 100}
                eval_res = await worker._call_minimax_evaluator(client, db, dummy_pos)
                logger.info(f"Evaluator result: {json.dumps(eval_res, indent=2)}")

def main():
    parser = argparse.ArgumentParser(description="Trigger AI Picks loops locally with verbose logging.")
    parser.add_argument("--mode", choices=["all", "hunter", "verifier", "evaluator"], default="all",
                        help="Which loop to run (default: all)")
    args = parser.parse_args()
    
    try:
        asyncio.run(run(mode=args.mode))
    except KeyboardInterrupt:
        logger.info("\nCancelled by user.")

if __name__ == "__main__":
    main()
