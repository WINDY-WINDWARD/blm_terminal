"""AI-tool implementations for Script Lab (Phase 4a).

Five tools, called from ``ai_chat_service._execute_tool`` dispatch — NOT from
the UI. Each opens its own session (mirroring ``mcp_server.*``) and resolves
the user from the ``current_user_id`` ContextVar the chat router sets.

Route-handler reuse: create/revise share the exact validation + persistence
logic of the HTTP endpoints by calling the router functions directly with a
duck-typed user (handlers only touch ``current_user.id``). Imports are
function-local to avoid a router-package import cycle at module load.

Mutation tools return a ``script_card`` key alongside the compact result.
``ai_chat_service`` pops it into an SSE ``script_card`` event (the Accept /
Discard card in the AI widget) and forwards the rest to the model.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from app.auth import current_user_id
from app.database import AsyncSessionLocal
from app.models.script import SavedScript, ScriptRevision

logger = logging.getLogger(__name__)


async def _user_id() -> int:
    uid = current_user_id.get()
    if uid is None:
        raise RuntimeError(
            "current_user_id is not set; script AI tools require a chat request context"
        )
    return uid


def _compact_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": manifest.get("name"),
        "params": manifest.get("params", []),
        "outputs": manifest.get("outputs", []),
        "needs_fundamentals": bool(manifest.get("needs_fundamentals", False)),
    }


async def list_scripts() -> list[dict[str, Any]]:
    """List the user's live scripts (builtins seeded lazily), head rev only."""
    from app.services import script_seeds

    async with AsyncSessionLocal() as db:
        user_id = await _user_id()
        await script_seeds.ensure_builtin_seeds(db, user_id)
        q = (
            select(SavedScript, ScriptRevision.rev_no)
            .outerjoin(ScriptRevision, ScriptRevision.id == SavedScript.head_rev_id)
            .where(SavedScript.user_id == user_id, SavedScript.deleted_at.is_(None))
            .order_by(SavedScript.is_builtin.desc(), SavedScript.name)
        )
        rows = (await db.execute(q)).all()
        return [
            {
                "script_id": s.id,
                "name": s.name,
                "description": s.description or "",
                "is_builtin": bool(s.is_builtin),
                "head_rev_no": rev_no,
            }
            for s, rev_no in rows
        ]


async def get_script(script_id: int) -> dict[str, Any]:
    """Return the head revision (manifest + code) plus revision count.

    The model needs the current code to write a revision; history bodies are
    omitted to keep context small — rollback targets are listed by rev_no.
    """
    from app.routers.scripts import _get_script, _head_rev

    async with AsyncSessionLocal() as db:
        user_id = await _user_id()
        script = await _get_script(db, user_id, int(script_id))
        head = await _head_rev(db, script)
        rev_count = (
            await db.execute(
                select(ScriptRevision.rev_no)
                .where(ScriptRevision.script_id == script.id)
                .order_by(ScriptRevision.rev_no.asc())
            )
        ).scalars().all()
        return {
            "script_id": script.id,
            "name": script.name,
            "description": script.description or "",
            "is_builtin": bool(script.is_builtin),
            "head_rev_no": head.rev_no if head else None,
            "rev_nos": list(rev_count),
            "manifest": _compact_manifest(dict(head.manifest)) if head else None,
            "code": head.code if head else None,
            "note": (head.note or "") if head else "",
        }


async def validate_script_code(code: str) -> dict[str, Any]:
    """Schema + static validation only. The backend never executes JS."""
    from app.schemas.script import validate_script

    manifest, errors = validate_script(code)
    if manifest is None:
        return {"valid": False, "errors": errors}
    return {
        "valid": not errors,
        "errors": errors,
        "name": manifest.name,
        "outputs": [o.id for o in manifest.outputs],
        "params": [p.key for p in manifest.params],
    }


async def create_script(
    name: str,
    code: str,
    description: str = "",
    note: str = "",
    chat_session_id: int | None = None,
) -> dict[str, Any]:
    """Validate then save as rev 1. Name must be unique per user."""
    from app.routers.scripts import create_script as _create_route
    from app.schemas.script import ScriptCreateIn

    async with AsyncSessionLocal() as db:
        user = SimpleNamespace(id=await _user_id())
        detail = await _create_route(
            ScriptCreateIn(
                name=name, description=description or "",
                code=code, note=note or "", chat_session_id=chat_session_id,
            ),
            user,  # type: ignore[arg-type] — handlers only read .id
            db,
        )
    head = detail.head
    return {
        "script_id": detail.id,
        "name": detail.name,
        "rev_no": detail.head_rev_no,
        "outputs": [o["id"] for o in head.manifest["outputs"]] if head else [],
        "params": [p["key"] for p in head.manifest.get("params", [])] if head else [],
        "script_card": {
            "action": "created",
            "script_id": detail.id,
            "name": detail.name,
            "rev_no": detail.head_rev_no,
        },
    }


async def revise_script(
    script_id: int,
    code: str,
    note: str = "",
    chat_session_id: int | None = None,
) -> dict[str, Any]:
    """Validate then append rev N+1 (builtins rejected; params auto-migrated)."""
    from app.routers.scripts import revise_script as _revise_route
    from app.schemas.script import ScriptReviseIn

    async with AsyncSessionLocal() as db:
        user = SimpleNamespace(id=await _user_id())
        detail = await _revise_route(
            int(script_id),
            ScriptReviseIn(code=code, note=note or "", chat_session_id=chat_session_id),
            user,  # type: ignore[arg-type] — handlers only read .id
            db,
        )
    head = detail.head
    return {
        "script_id": detail.id,
        "name": detail.name,
        "rev_no": detail.head_rev_no,
        "outputs": [o["id"] for o in head.manifest["outputs"]] if head else [],
        "params": [p["key"] for p in head.manifest.get("params", [])] if head else [],
        "script_card": {
            "action": "revised",
            "script_id": detail.id,
            "name": detail.name,
            "rev_no": detail.head_rev_no,
        },
    }
