"""Execution runner for automated scheduled AI workflows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any
import zoneinfo

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.ai_chat import ChatMessageRecord, ChatSession
from app.models.ai_workflow import AiWorkflow, AiWorkflowRun
from app.services.ai_chat_service import BLM_TOOLS, _run_tools_parallel
from app.services.ai_config import resolve_workflow_model
from app.services.llm_provider import stream_chat_completion
from app.services.prompts import UNATTENDED_RUN_PROMPT

logger = logging.getLogger(__name__)

DENIED_ALWAYS: frozenset[str] = frozenset({
    "create_script",
    "revise_script",
    "create_workflow",
    "manage_workflows",
    "create_custom_prompt",
    "manage_custom_prompts",
})

DENIED_UNLESS_WRITE: frozenset[str] = frozenset({
    "open_position",
    "add_position_leg",
    "update_position_leg",
    "delete_position_leg",
    "delete_position",
    "add_watchlist_item",
    "remove_watchlist_item",
    "create_watchlist",
    "bulk_replace_watchlist",
})


def allowed_tool_names(allow_write: bool) -> set[str]:
    """Return the set of tool names permitted for scheduled workflow execution."""
    denied = DENIED_ALWAYS if allow_write else (DENIED_ALWAYS | DENIED_UNLESS_WRITE)
    return {
        t["function"]["name"]
        for t in BLM_TOOLS
        if t.get("function", {}).get("name") not in denied
    }


def allowed_tool_schemas(allow_write: bool) -> list[dict[str, Any]]:
    """Return the list of tool schemas from BLM_TOOLS permitted for workflow execution."""
    allowed = allowed_tool_names(allow_write)
    return [t for t in BLM_TOOLS if t.get("function", {}).get("name") in allowed]


async def _execute_workflow_run(workflow_id: int, run_id: int) -> str:
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        workflow = await db.get(AiWorkflow, workflow_id)

        # 1. Claim the run atomically. The sweep and a manual trigger must never
        #    execute the same row twice.
        claim = await db.execute(
            update(AiWorkflowRun)
            .where(AiWorkflowRun.id == run_id, AiWorkflowRun.status == "queued")
            .values(status="running", started_at=started_at)
        )
        await db.commit()
        if claim.rowcount == 0:
            logger.info("Run %d was already claimed; skipping", run_id)
            return "skipped:already-claimed"

        run = await db.get(AiWorkflowRun, run_id, populate_existing=True)
        if not run or not workflow:
            return f"error:Run {run_id} or workflow {workflow_id} not found"

        try:
            # 2. Resolve the model: pinned model, then the hunter model, then the
            #    first model the active route actually serves.
            model = await resolve_workflow_model(workflow.model, db)

            today = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
            name_label = run.name_snapshot or workflow.name
            session_title = f"[Workflow] {name_label} · {today} IST"

            first_sym = ""
            try:
                syms = json.loads(workflow.symbols_json or "[]")
                if isinstance(syms, list) and syms:
                    first_sym = str(syms[0])
            except Exception:
                pass

            session = ChatSession(
                user_id=run.user_id,
                title=session_title,
                model=model,
                symbol=first_sym,
                exchange="NSE",
            )
            db.add(session)
            await db.flush()

            run.session_id = session.id

            user_content = run.prompt_snapshot or workflow.prompt
            user_msg = ChatMessageRecord(
                session_id=session.id,
                role="user",
                content=user_content,
            )
            db.add(user_msg)
            await db.commit()
            await db.refresh(session)

            # 3. System prompt = UNATTENDED_RUN_PROMPT + newline + name, symbols, and watchlist scope
            scope_parts = [f"Workflow: {workflow.name}"]
            if workflow.symbols_json and workflow.symbols_json != "[]":
                scope_parts.append(f"Symbols: {workflow.symbols_json}")
            if workflow.watchlist_id:
                scope_parts.append(f"Watchlist ID: {workflow.watchlist_id}")
            system_prompt = f"{UNATTENDED_RUN_PROMPT}\n" + "\n".join(scope_parts)

            # 4. messages = [{"role": "user", "content": run.prompt_snapshot}]
            user_content = run.prompt_snapshot or workflow.prompt
            messages = [{"role": "user", "content": user_content}]

            # 5. Build executor closure enforcing deny list at execution time
            seen_calls: set[str] = set()

            async def executor(tool_calls: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
                allowed = allowed_tool_names(workflow.allow_write_tools)
                allowed_calls: list[dict[str, Any]] = []
                denied_events: list[str] = []
                denied_msgs: list[dict[str, Any]] = []

                for tc in tool_calls:
                    name = tc.get("name", "")
                    tc_id = tc.get("id", "")
                    if name not in allowed:
                        msg_str = f"Tool {name} is not permitted in scheduled runs."
                        denied_events.append(
                            json.dumps({"type": "tool_result", "name": name, "preview": msg_str[:120]})
                        )
                        denied_msgs.append({"id": tc_id, "name": name, "content": msg_str})
                    else:
                        allowed_calls.append(tc)

                allowed_events: list[str] = []
                allowed_msgs: list[dict[str, Any]] = []
                if allowed_calls:
                    allowed_events, allowed_msgs = await _run_tools_parallel(
                        allowed_calls,
                        seen_calls,
                        session_id=session.id,
                        user_id=run.user_id,
                    )

                # Combine messages matching tool_calls order
                all_msgs_by_id = {m["id"]: m for m in allowed_msgs}
                all_msgs_by_id.update({m["id"]: m for m in denied_msgs})
                combined_msgs = [
                    all_msgs_by_id[tc["id"]]
                    for tc in tool_calls
                    if tc.get("id") in all_msgs_by_id
                ]

                return allowed_events + denied_events, combined_msgs

            # 6. Call stream_chat_completion
            full_content = ""
            async for chunk in stream_chat_completion(
                messages=messages,
                model=model,
                tools=allowed_tool_schemas(workflow.allow_write_tools),
                tool_executor=executor,
                system_prompt=system_prompt,
                max_iter=40,
                allow_external_route=True,
                first_delta_deadline=600.0,
                idle_delta_deadline=600.0,
            ):
                evt = json.loads(chunk)
                if evt.get("type") == "token":
                    full_content += evt.get("text", "")
                elif evt.get("type") == "error":
                    err_class = evt.get("error_class", "")
                    msg = evt.get("message", "API error")
                    err_prefix = f" [{err_class}]" if err_class else ""
                    raise RuntimeError(f"AI provider error{err_prefix}: {msg}")

            # 7. Persist assistant text as ChatMessageRecord row
            assistant_msg = ChatMessageRecord(
                session_id=session.id,
                role="assistant",
                content=full_content,
            )
            db.add(assistant_msg)

            # 8. Check if output strips to [SILENT]
            finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)

            run.finished_at = finished_at
            run.duration_ms = max(0, duration_ms)
            run.output_text = full_content

            is_silent = (full_content.strip() == "[SILENT]")
            if is_silent:
                run.status = "succeeded"
                run.is_silent = True
                run.output_summary = "No findings"
            else:
                run.status = "succeeded"
                run.is_silent = False
                non_empty_lines = [line.strip() for line in full_content.splitlines() if line.strip()]
                summary = " ".join(non_empty_lines[:2])
                run.output_summary = summary[:512] if summary else "No findings"

            # 9. Set last_run_at and last_success_at on success
            workflow.last_run_at = finished_at
            workflow.last_success_at = finished_at
            await db.commit()

            return "silent" if is_silent else "ok"

        except Exception as exc:
            logger.error("Workflow run %d failed: %s", run_id, exc, exc_info=True)
            finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            err_text = str(exc)[:2000]
            run.status = "failed"
            run.finished_at = finished_at
            run.duration_ms = max(0, duration_ms)
            run.error = err_text
            workflow.last_run_at = finished_at

            # Ensure session exists and failure assistant message is recorded
            if run.session_id:
                try:
                    stmt = select(ChatMessageRecord).where(
                        ChatMessageRecord.session_id == run.session_id,
                        ChatMessageRecord.role == "assistant",
                    )
                    existing_assistant = (await db.execute(stmt)).scalars().first()
                    if not existing_assistant:
                        db.add(
                            ChatMessageRecord(
                                session_id=run.session_id,
                                role="assistant",
                                content=f"⚠ {err_text}",
                            )
                        )
                except Exception as msg_err:
                    logger.warning("Failed to record error chat message for run %d: %s", run_id, msg_err)

            await db.commit()
            return f"error:{str(exc)[:500]}"


async def run_workflow(workflow_id: int, run_id: int) -> str:
    """Run an AI workflow execution run with a 900-second timeout."""
    try:
        return await asyncio.wait_for(_execute_workflow_run(workflow_id, run_id), timeout=900.0)
    except asyncio.TimeoutError:
        logger.error("Workflow run %d timed out after 900 seconds", run_id)
        async with AsyncSessionLocal() as db:
            run = await db.get(AiWorkflowRun, run_id)
            wf = await db.get(AiWorkflow, workflow_id)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            err_msg = "Workflow run timed out after 900 seconds"
            if run:
                run.status = "failed"
                run.finished_at = now
                if run.started_at:
                    run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
                run.error = err_msg

                if run.session_id:
                    try:
                        stmt = select(ChatMessageRecord).where(
                            ChatMessageRecord.session_id == run.session_id,
                            ChatMessageRecord.role == "assistant",
                        )
                        existing_assistant = (await db.execute(stmt)).scalars().first()
                        if not existing_assistant:
                            db.add(
                                ChatMessageRecord(
                                    session_id=run.session_id,
                                    role="assistant",
                                    content=f"⚠ {err_msg}",
                                )
                            )
                    except Exception as msg_err:
                        logger.warning("Failed to record timeout chat message for run %d: %s", run_id, msg_err)
            if wf:
                wf.last_run_at = now
            await db.commit()
        return "error:Workflow run timed out after 900 seconds"
