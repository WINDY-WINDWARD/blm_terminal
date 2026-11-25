"""Tests for the high-risk OAuth provider gate and acknowledgements."""

from __future__ import annotations

import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.models.system_config import SystemConfig
from app.services.provider_risk_gate import (
    ACK_CONFIG_KEY,
    GATE_CONFIG_KEY,
    RISK_GATE_VERSION,
    RISKY_OAUTH_ROUTES,
    ack_is_current,
    apply_risk_gate,
    build_risk_info,
    get_risk_ack_map,
    is_risk_acknowledged,
    is_risky_route,
    record_risk_acknowledgement,
    risky_route_id_for_provider,
)
from app.services.route_registry import DEFAULT_ROUTE_ID


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _seed_route(
    session: AsyncSession,
    route_id: str,
    provider: str,
    *,
    enabled: bool = True,
    display_label: str | None = None,
) -> AIProviderRoute:
    route = AIProviderRoute(
        id=route_id,
        kind="oauth",
        provider=provider,
        display_label=display_label or provider.capitalize(),
        proxy_prefix=f"blm-{provider}",
        enabled=enabled,
        config_json="{}",
    )
    session.add(route)
    return route


def _seed_account(
    session: AsyncSession,
    route_id: str,
    account_id: str,
    *,
    enabled: bool = True,
    status: str = "active",
) -> AIProviderCredential:
    cred = AIProviderCredential(
        id=account_id,
        route_id=route_id,
        kind="oauth",
        vault_reference=f"vault:{account_id}",
        proxy_credential_name=account_id,
        masked_identity=f"{account_id}@example.com",
        priority=1,
        weight=1,
        enabled=enabled,
        status=status,
    )
    session.add(cred)
    return cred


def test_policy_constants_and_helpers() -> None:
    assert RISK_GATE_VERSION == "2026.11.25"
    assert set(RISKY_OAUTH_ROUTES) == {"oauth:antigravity", "oauth:claude"}
    assert RISKY_OAUTH_ROUTES["oauth:antigravity"]["label"] == "Gemini (Antigravity)"

    assert is_risky_route("oauth:antigravity") is True
    assert is_risky_route(" oauth:claude ") is True
    assert is_risky_route("oauth:codex") is False
    assert is_risky_route(None) is False

    assert risky_route_id_for_provider("gemini") == "oauth:antigravity"
    assert risky_route_id_for_provider("antigravity") == "oauth:antigravity"
    assert risky_route_id_for_provider("oauth:antigravity") == "oauth:antigravity"
    assert risky_route_id_for_provider("claude") == "oauth:claude"
    assert risky_route_id_for_provider("claude-code") == "oauth:claude"
    assert risky_route_id_for_provider("codex") is None


def test_build_risk_info_shape() -> None:
    assert build_risk_info("oauth:codex") is None

    info = build_risk_info("oauth:claude", acknowledged=False, auto_disabled=True)
    assert info is not None
    assert info["level"] == "high"
    assert info["acknowledged"] is False
    assert info["auto_disabled"] is True
    assert info["gate_version"] == RISK_GATE_VERSION
    assert "ban" in info["title"].lower()
    assert "ban" in info["message"].lower()


async def test_acknowledgement_round_trip(session_factory) -> None:  # noqa: ANN001
    async with session_factory() as session:
        assert await is_risk_acknowledged(session, "oauth:codex") is True
        assert await is_risk_acknowledged(session, "oauth:claude") is False
        assert await get_risk_ack_map(session) == {}

        with pytest.raises(ValueError):
            await record_risk_acknowledgement(session, "oauth:codex", "1")

        await record_risk_acknowledgement(session, "oauth:claude", "42")

        assert await is_risk_acknowledged(session, "oauth:claude") is True
        assert await is_risk_acknowledged(session, "oauth:antigravity") is False

        ack_map = await get_risk_ack_map(session)
        assert ack_map["oauth:claude"]["version"] == RISK_GATE_VERSION
        assert ack_map["oauth:claude"]["accepted_by"] == "42"
        assert ack_is_current(ack_map["oauth:claude"]) is True

        row = (
            await session.execute(
                select(SystemConfig).where(SystemConfig.key == ACK_CONFIG_KEY)
            )
        ).scalar_one()
        stored = json.loads(row.value)
        assert stored["oauth:claude"]["accepted_at"]


async def test_invalid_ack_map_is_ignored(session_factory) -> None:  # noqa: ANN001
    async with session_factory() as session:
        session.add(SystemConfig(key=ACK_CONFIG_KEY, value="not-json"))
        await session.commit()

        assert await get_risk_ack_map(session) == {}
        assert ack_is_current({"version": "old"}) is False


async def test_apply_risk_gate_disables_only_risky_routes(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    promotion = AsyncMock(return_value=DEFAULT_ROUTE_ID)
    monkeypatch.setattr("app.routers.ai_routes.ensure_usable_active_route", promotion)

    async with session_factory() as session:
        _seed_route(session, "oauth:antigravity", "antigravity", display_label="Antigravity")
        _seed_route(session, "oauth:claude", "claude")
        _seed_route(session, "oauth:codex", "codex")
        _seed_account(session, "oauth:antigravity", "acc-gemini")
        _seed_account(session, "oauth:claude", "acc-claude")
        _seed_account(session, "oauth:codex", "acc-codex")
        session.add(SystemConfig(key="ai.provider", value="oauth:claude"))
        session.add(
            SystemConfig(
                key="ai.hunter_model",
                value="blm:oauth:antigravity/gemini-3.8-flash-high",
            )
        )
        session.add(
            SystemConfig(key="ai.verifier_model", value="blm:direct:openai/gpt-4o")
        )
        session.add(SystemConfig(key="unrelated.setting", value="keep"))
        await session.commit()

        assert await apply_risk_gate(session) is True
        promotion.assert_awaited_once()

        routes = {
            route.id: route
            for route in (await session.execute(select(AIProviderRoute))).scalars().all()
        }
        assert routes["oauth:antigravity"].enabled is False
        assert routes["oauth:antigravity"].display_label == "Gemini (Antigravity)"
        assert routes["oauth:claude"].enabled is False
        assert routes["oauth:codex"].enabled is True

        for route_id in ("oauth:antigravity", "oauth:claude"):
            creds = list(
                (
                    await session.execute(
                        select(AIProviderCredential).where(
                            AIProviderCredential.route_id == route_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert creds
            for cred in creds:
                assert cred.enabled is False
                assert cred.status == "disabled"
                assert cred.cooldown is None

        codex_cred = (
            await session.execute(
                select(AIProviderCredential).where(
                    AIProviderCredential.route_id == "oauth:codex"
                )
            )
        ).scalar_one()
        assert codex_cred.enabled is True
        assert codex_cred.status == "active"

        config = {
            row.key: row.value
            for row in (await session.execute(select(SystemConfig))).scalars().all()
        }
        assert config["ai.provider"] == DEFAULT_ROUTE_ID
        assert "ai.hunter_model" not in config
        assert config["ai.verifier_model"] == "blm:direct:openai/gpt-4o"
        assert config[GATE_CONFIG_KEY] == RISK_GATE_VERSION
        assert config["unrelated.setting"] == "keep"

        # Idempotent: a second run does not disable or promote again.
        assert await apply_risk_gate(session) is False
        promotion.assert_awaited_once()


async def test_disabled_antigravity_returns_no_static_models(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    from app.services.route_catalog import get_route_models

    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    async with session_factory() as session:
        _seed_route(session, "oauth:antigravity", "antigravity", enabled=False)
        await session.commit()

    with pytest.raises(ValueError, match="unavailable"):
        await get_route_models("oauth:antigravity")


async def test_apply_risk_gate_does_not_mark_incomplete_gate(session_factory) -> None:  # noqa: ANN001
    async with session_factory() as session:
        _seed_route(session, "oauth:antigravity", "antigravity")
        session.add(SystemConfig(key="ai.provider", value="oauth:antigravity"))
        await session.commit()

        assert await apply_risk_gate(session) is False

        gate_row = (
            await session.execute(
                select(SystemConfig).where(SystemConfig.key == GATE_CONFIG_KEY)
            )
        ).scalar_one_or_none()
        assert gate_row is None


async def test_apply_risk_gate_keeps_safe_active_route(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    promotion = AsyncMock(return_value=None)
    monkeypatch.setattr("app.routers.ai_routes.ensure_usable_active_route", promotion)

    async with session_factory() as session:
        _seed_route(session, "oauth:antigravity", "antigravity")
        _seed_route(session, "oauth:claude", "claude")
        _seed_route(session, "oauth:codex", "codex")
        session.add(SystemConfig(key="ai.provider", value="oauth:codex"))
        await session.commit()

        assert await apply_risk_gate(session) is True

        provider_row = (
            await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "ai.provider")
            )
        ).scalar_one()
        assert provider_row == "oauth:codex"