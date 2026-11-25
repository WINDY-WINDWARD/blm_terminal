"""AI-tool implementations for scheduled workflows and custom prompts.

Called from ai_chat_service._execute_tool dispatch. Resolves the user
from the current_user_id ContextVar.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.auth import current_user_id
from app.database import AsyncSessionLocal
from app.models.ai_workflow import AiCustomPrompt, AiWorkflow, AiWorkflowRun
from app.services.workflow_schedule import (
    build_cron,
    default_catch_up_hours,
    describe,
    next_run,
    validate_cron,
)

logger = logging.getLogger(__name__)


def _user_id() -> int:
    uid = current_user_id.get()
    if uid is None:
        raise RuntimeError("No authenticated user")
    return uid


async def create_workflow(
    name: str,
    prompt: str,
    schedule_type: str,
    time_of_day: str | None = None,
    days_of_week: list[int] | str | None = None,
    cron: str | None = None,
    symbols: list[str] | None = None,
    catch_up_enabled: bool = True,
    allow_write_tools: bool = False,
) -> dict[str, Any]:
    user_id = _user_id()
    tz = "Asia/Kolkata"

    if schedule_type == "custom":
        if not cron:
            raise ValueError("cron is required for custom schedule")
        cron_expr = cron
    else:
        cron_expr = build_cron(
            schedule_type,
            time_of_day=time_of_day,
            days_of_week=days_of_week,
            tz=tz,
        )

    validate_cron(cron_expr, tz=tz)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    next_run_dt = next_run(cron_expr, tz, now_utc)

    days_of_week_str = None
    if days_of_week is not None:
        if isinstance(days_of_week, (list, tuple, set)):
            days_of_week_str = ",".join(str(d) for d in sorted(days_of_week))
        else:
            days_of_week_str = str(days_of_week)

    symbols_list = symbols if isinstance(symbols, list) else []
    symbols_str = json.dumps(symbols_list)
    catch_up_window = default_catch_up_hours(schedule_type)

    async with AsyncSessionLocal() as db:
        wf = AiWorkflow(
            user_id=user_id,
            name=name,
            prompt=prompt,
            schedule_type=schedule_type,
            cron_expression=cron_expr,
            timezone=tz,
            time_of_day=time_of_day,
            days_of_week=days_of_week_str,
            symbols_json=symbols_str,
            catch_up_enabled=catch_up_enabled,
            catch_up_window_hours=catch_up_window,
            allow_write_tools=allow_write_tools,
            is_enabled=True,
            next_run_at=next_run_dt,
        )
        db.add(wf)
        await db.commit()
        await db.refresh(wf)

        schedule_lbl = describe(wf.schedule_type, wf.cron_expression, wf.timezone)
        next_iso = wf.next_run_at.isoformat() if wf.next_run_at else None

        return {
            "ok": True,
            "workflow_id": wf.id,
            "next_run_at": next_iso,
            "workflow_card": {
                "id": wf.id,
                "name": wf.name,
                "schedule_label": schedule_lbl,
                "next_run_at": next_iso,
                "symbols": symbols_list,
                "status": "created",
            },
        }


async def manage_workflows(
    action: str,
    workflow_id: int | None = None,
    name: str | None = None,
    prompt: str | None = None,
    schedule_type: str | None = None,
    time_of_day: str | None = None,
    days_of_week: list[int] | str | None = None,
    cron: str | None = None,
    catch_up_enabled: bool | None = None,
    allow_write_tools: bool | None = None,
) -> dict[str, Any]:
    user_id = _user_id()
    if action not in ("list", "pause", "resume", "delete", "run", "update"):
        raise ValueError(f"Unsupported action: {action}")

    async with AsyncSessionLocal() as db:
        if action == "list":
            stmt = (
                select(AiWorkflow)
                .where(AiWorkflow.user_id == user_id, AiWorkflow.deleted_at.is_(None))
                .order_by(AiWorkflow.next_run_at.asc().nulls_last(), AiWorkflow.id.asc())
            )
            workflows = (await db.execute(stmt)).scalars().all()
            results = []
            for wf in workflows:
                try:
                    syms = json.loads(wf.symbols_json) if wf.symbols_json else []
                except Exception:
                    syms = []
                results.append({
                    "id": wf.id,
                    "name": wf.name,
                    "prompt": wf.prompt,
                    "schedule_type": wf.schedule_type,
                    "schedule_label": describe(wf.schedule_type, wf.cron_expression, wf.timezone),
                    "is_enabled": wf.is_enabled,
                    "next_run_at": wf.next_run_at.isoformat() if wf.next_run_at else None,
                    "last_run_at": wf.last_run_at.isoformat() if wf.last_run_at else None,
                    "symbols": syms,
                    "allow_write_tools": wf.allow_write_tools,
                })
            return {"ok": True, "workflows": results}

        if workflow_id is None:
            raise ValueError(f"workflow_id is required for action '{action}'")

        stmt = select(AiWorkflow).where(
            AiWorkflow.id == workflow_id,
            AiWorkflow.user_id == user_id,
            AiWorkflow.deleted_at.is_(None),
        )
        wf = (await db.execute(stmt)).scalar_one_or_none()
        if wf is None:
            raise ValueError(f"Workflow {workflow_id} not found")

        if action == "pause":
            wf.is_enabled = False
            wf.next_run_at = None
            await db.commit()
            return {"ok": True, "action": "pause", "workflow_id": wf.id, "is_enabled": False}

        if action == "resume":
            wf.is_enabled = True
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            wf.next_run_at = next_run(wf.cron_expression, wf.timezone, now_utc)
            await db.commit()
            return {
                "ok": True,
                "action": "resume",
                "workflow_id": wf.id,
                "is_enabled": True,
                "next_run_at": wf.next_run_at.isoformat() if wf.next_run_at else None,
            }

        if action == "delete":
            wf.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            wf.is_enabled = False
            wf.next_run_at = None
            await db.commit()
            return {"ok": True, "action": "delete", "workflow_id": wf.id}

        if action == "run":
            active_check = await db.execute(
                select(AiWorkflowRun).where(
                    AiWorkflowRun.workflow_id == wf.id,
                    AiWorkflowRun.status.in_(["queued", "running"]),
                )
            )
            if active_check.scalars().first() is not None:
                return {
                    "ok": False,
                    "error": "A run is already queued or running for this workflow",
                    "workflow_id": wf.id,
                }

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            slot_k = f"{wf.id}:manual:{int(now_utc.timestamp())}"
            run = AiWorkflowRun(
                workflow_id=wf.id,
                user_id=user_id,
                trigger="manual",
                status="queued",
                scheduled_for=now_utc,
                slot_key=slot_k,
                name_snapshot=wf.name,
                prompt_snapshot=wf.prompt,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return {
                "ok": True,
                "action": "run",
                "workflow_id": wf.id,
                "run_id": run.id,
                "status": "queued",
            }

        # action == "update" (MUST NOT write)
        candidate_changes: dict[str, Any] = {
            "name": name,
            "prompt": prompt,
            "schedule_type": schedule_type,
            "time_of_day": time_of_day,
            "days_of_week": days_of_week,
            "cron": cron,
            "catch_up_enabled": catch_up_enabled,
            "allow_write_tools": allow_write_tools,
        }
        changes = {k: v for k, v in candidate_changes.items() if v is not None}

        p_type = schedule_type if schedule_type is not None else wf.schedule_type
        p_tod = time_of_day if time_of_day is not None else wf.time_of_day
        p_dow = days_of_week if days_of_week is not None else wf.days_of_week
        p_cron = cron if cron is not None else wf.cron_expression

        try:
            if p_type == "custom":
                calc_cron = p_cron
            else:
                calc_cron = build_cron(p_type, time_of_day=p_tod, days_of_week=p_dow, tz=wf.timezone)
            schedule_label = describe(p_type, calc_cron, wf.timezone)
        except Exception:
            schedule_label = describe(wf.schedule_type, wf.cron_expression, wf.timezone)

        return {
            "ok": True,
            "proposed": True,
            "instruction": "Edit proposed. The user must click Apply.",
            "workflow_card": {
                "id": wf.id,
                "name": name if name is not None else wf.name,
                "schedule_label": schedule_label,
                "status": "proposed",
                "changes": changes,
                "previous": {
                    "name": wf.name,
                    "prompt": wf.prompt,
                    "schedule_type": wf.schedule_type,
                    "time_of_day": wf.time_of_day,
                    "days_of_week": wf.days_of_week,
                },
            },
        }


async def create_custom_prompt(
    title: str,
    tag: str,
    description: str,
    prompt: str,
    mode: str = "research",
) -> dict[str, Any]:
    user_id = _user_id()
    async with AsyncSessionLocal() as db:
        max_order_stmt = select(func.max(AiCustomPrompt.sort_order)).where(
            AiCustomPrompt.user_id == user_id,
            AiCustomPrompt.deleted_at.is_(None),
        )
        max_order = (await db.execute(max_order_stmt)).scalar()
        sort_order = 0 if max_order is None else max_order + 1

        p = AiCustomPrompt(
            user_id=user_id,
            title=title,
            tag=tag,
            description=description,
            prompt=prompt,
            mode=mode or "research",
            sort_order=sort_order,
        )
        db.add(p)
        await db.commit()
        await db.refresh(p)

        return {
            "ok": True,
            "prompt_id": p.id,
            "prompt_card": {
                "id": p.id,
                "title": p.title,
                "tag": p.tag,
                "description": p.description or "",
                "prompt": p.prompt,
                "mode": p.mode,
                "status": "created",
            },
        }


async def manage_custom_prompts(
    action: str,
    prompt_id: int | None = None,
    title: str | None = None,
    tag: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    user_id = _user_id()
    if action not in ("list", "delete", "update"):
        raise ValueError(f"Unsupported action: {action}")

    async with AsyncSessionLocal() as db:
        if action == "list":
            stmt = (
                select(AiCustomPrompt)
                .where(AiCustomPrompt.user_id == user_id, AiCustomPrompt.deleted_at.is_(None))
                .order_by(AiCustomPrompt.sort_order.asc(), AiCustomPrompt.id.asc())
            )
            prompts = (await db.execute(stmt)).scalars().all()
            return {
                "ok": True,
                "prompts": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "tag": p.tag,
                        "description": p.description or "",
                        "prompt": p.prompt,
                        "mode": p.mode,
                        "sort_order": p.sort_order,
                        "use_count": p.use_count,
                    }
                    for p in prompts
                ],
            }

        if prompt_id is None:
            raise ValueError(f"prompt_id is required for action '{action}'")

        stmt = select(AiCustomPrompt).where(
            AiCustomPrompt.id == prompt_id,
            AiCustomPrompt.user_id == user_id,
            AiCustomPrompt.deleted_at.is_(None),
        )
        prompt_item = (await db.execute(stmt)).scalar_one_or_none()
        if prompt_item is None:
            raise ValueError(f"Custom prompt {prompt_id} not found")

        if action == "delete":
            prompt_item.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            return {"ok": True, "action": "delete", "prompt_id": prompt_item.id}

        # action == "update" (MUST NOT write)
        candidate_changes: dict[str, Any] = {
            "title": title,
            "tag": tag,
            "description": description,
            "prompt": prompt,
        }
        changes = {k: v for k, v in candidate_changes.items() if v is not None}

        return {
            "ok": True,
            "proposed": True,
            "instruction": "Edit proposed. The user must click Apply.",
            "prompt_card": {
                "id": prompt_item.id,
                "title": title if title is not None else prompt_item.title,
                "status": "proposed",
                "changes": changes,
                "previous": {
                    "title": prompt_item.title,
                    "tag": prompt_item.tag,
                    "description": prompt_item.description or "",
                    "prompt": prompt_item.prompt,
                },
            },
        }
