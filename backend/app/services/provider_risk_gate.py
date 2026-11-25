"""Risk policy for unofficial OAuth routes that can get a user account banned.

The Gemini (Antigravity) and Claude OAuth routes reuse a personal subscription
through an unofficial client. The provider can suspend or permanently ban the
account. This module holds the policy, the one-time auto-disable gate, and the
user acknowledgements.

Policy surface:

* ``RISKY_OAUTH_ROUTES`` - the route spec shown in the UI and the docs.
* ``apply_risk_gate`` - one-time gate that disables the risky routes and
  credentials, then re-promotes a usable default route.
* ``record_risk_acknowledgement`` - installation-wide acceptance of the risk
  notice, recorded with the accepting user.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_provider import AIProviderRoute
from app.models.system_config import SystemConfig
from app.services.route_registry import (
    DEFAULT_ROUTE_ID,
    parse_route_model_id,
    provider_to_route_id,
)

logger = logging.getLogger(__name__)

RISK_GATE_VERSION = "2026.11.25"
GATE_CONFIG_KEY = "ai.provider_risk_gate"
ACK_CONFIG_KEY = "ai.risky_provider_ack"
RISKY_MODEL_CONFIG_KEYS: tuple[str, ...] = ("ai.hunter_model", "ai.verifier_model")

_RISK_TITLE = "DO NOT USE - HIGH RISK OF ACCOUNT BAN"
_RISK_MESSAGE = (
    "This route uses a personal subscription through an unofficial client. "
    "The provider can suspend or permanently ban the account. "
    "BLM Terminal cannot recover a banned account."
)

RISKY_OAUTH_ROUTES: dict[str, dict[str, str]] = {
    "oauth:antigravity": {
        "provider": "antigravity",
        "label": "Gemini (Antigravity)",
        "title": _RISK_TITLE,
        "message": _RISK_MESSAGE,
    },
    "oauth:claude": {
        "provider": "claude",
        "label": "Claude",
        "title": _RISK_TITLE,
        "message": _RISK_MESSAGE,
    },
}

RISKY_OAUTH_PROVIDERS: tuple[str, ...] = ("antigravity", "claude")


def is_risky_route(route_id: str | None) -> bool:
    """Return True when the route ID is one of the banned-risk OAuth routes."""
    if not route_id or not isinstance(route_id, str):
        return False
    return route_id.strip() in RISKY_OAUTH_ROUTES


def risky_route_id_for_provider(provider: str | None) -> str | None:
    """Map a provider name to its risky route ID, or None when not risky."""
    if not provider or not isinstance(provider, str):
        return None

    p = provider.strip().lower()
    if p.startswith("oauth:"):
        p = p.split(":", 1)[1]
    if p in ("gemini", "antigravity"):
        return "oauth:antigravity"
    if p in ("claude", "claude-code"):
        return "oauth:claude"
    return None


async def get_risk_ack_map(session: AsyncSession) -> dict[str, dict[str, Any]]:
    """Load the acknowledgement map from SystemConfig. Missing or invalid data returns {}."""
    res = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == ACK_CONFIG_KEY)
    )
    raw = res.scalar_one_or_none()
    if not raw or not raw.strip():
        return {}

    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("get_risk_ack_map: failed to parse %s (%s)", ACK_CONFIG_KEY, exc)
        return {}

    if not isinstance(data, dict):
        return {}

    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def ack_is_current(ack: dict[str, Any] | None) -> bool:
    """Return True when the acknowledgement matches the current gate version."""
    if not isinstance(ack, dict):
        return False
    return ack.get("version") == RISK_GATE_VERSION


async def is_risk_acknowledged(session: AsyncSession, route_id: str) -> bool:
    """Return True for non-risky routes and for risky routes with a current acknowledgement."""
    if not is_risky_route(route_id):
        return True

    acks = await get_risk_ack_map(session)
    return ack_is_current(acks.get(route_id.strip()))


def build_risk_info(
    route_id: str | None,
    acknowledged: bool = False,
    auto_disabled: bool = False,
) -> dict[str, Any] | None:
    """Build the risk notice payload for a route, or None when the route is not risky."""
    if not is_risky_route(route_id):
        return None

    spec = RISKY_OAUTH_ROUTES[route_id.strip()]
    return {
        "level": "high",
        "title": spec["title"],
        "message": spec["message"],
        "acknowledged": bool(acknowledged),
        "gate_version": RISK_GATE_VERSION,
        "auto_disabled": bool(auto_disabled),
    }


async def record_risk_acknowledgement(
    session: AsyncSession, route_id: str, user_id: str
) -> None:
    """Store an installation-wide acknowledgement for a risky route and commit it."""
    if not is_risky_route(route_id):
        raise ValueError(f"Route '{route_id}' is not a risky OAuth route")

    clean_id = route_id.strip()
    acks = await get_risk_ack_map(session)
    acks[clean_id] = {
        "version": RISK_GATE_VERSION,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "accepted_by": str(user_id),
    }

    raw = json.dumps(acks, sort_keys=True)
    row = (
        await session.execute(
            select(SystemConfig).where(SystemConfig.key == ACK_CONFIG_KEY)
        )
    ).scalar_one_or_none()
    if row is not None:
        row.value = raw
    else:
        session.add(SystemConfig(key=ACK_CONFIG_KEY, value=raw))

    await session.commit()


async def apply_risk_gate(session: AsyncSession) -> bool:
    """Apply the one-time risky-route gate.

    Returns False when the gate already ran at the current version. Returns True
    after disabling the risky routes and credentials, clearing risky selections,
    and committing. Route promotion failures are logged, never raised.
    """
    gate_res = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == GATE_CONFIG_KEY)
    )
    if (gate_res.scalar_one_or_none() or "").strip() == RISK_GATE_VERSION:
        return False

    route_ids = list(RISKY_OAUTH_ROUTES.keys())
    routes_res = await session.execute(
        select(AIProviderRoute)
        .options(selectinload(AIProviderRoute.credentials))
        .where(AIProviderRoute.id.in_(route_ids))
    )
    routes = {route.id: route for route in routes_res.scalars().all()}

    missing = [route_id for route_id in route_ids if route_id not in routes]
    if missing:
        logger.warning(
            "apply_risk_gate: risky routes missing (%s); gate not marked complete",
            ", ".join(missing),
        )
        return False

    for route_id, spec in RISKY_OAUTH_ROUTES.items():
        route = routes.get(route_id)
        if route is None:
            continue
        route.enabled = False
        route.display_label = spec["label"]
        for credential in route.credentials:
            credential.enabled = False
            credential.status = "disabled"
            credential.cooldown = None

    provider_row = (
        await session.execute(
            select(SystemConfig).where(SystemConfig.key == "ai.provider")
        )
    ).scalar_one_or_none()
    if provider_row is not None and is_risky_route(provider_to_route_id(provider_row.value)):
        provider_row.value = DEFAULT_ROUTE_ID

    for key in RISKY_MODEL_CONFIG_KEYS:
        model_row = (
            await session.execute(select(SystemConfig).where(SystemConfig.key == key))
        ).scalar_one_or_none()
        if model_row is None:
            continue
        try:
            model_route_id, _ = parse_route_model_id(model_row.value or "")
        except ValueError:
            continue
        if is_risky_route(model_route_id):
            await session.delete(model_row)

    gate_row = (
        await session.execute(
            select(SystemConfig).where(SystemConfig.key == GATE_CONFIG_KEY)
        )
    ).scalar_one_or_none()
    if gate_row is not None:
        gate_row.value = RISK_GATE_VERSION
    else:
        session.add(SystemConfig(key=GATE_CONFIG_KEY, value=RISK_GATE_VERSION))

    await session.commit()

    try:
        from app.routers.ai_routes import ensure_usable_active_route

        await ensure_usable_active_route(session)
    except Exception as exc:
        logger.warning("apply_risk_gate: route promotion failed (%s)", exc)

    return True
