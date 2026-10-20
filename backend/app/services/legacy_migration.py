"""Legacy migration service for AI providers, models, and credentials.

Enforces:
- Non-destructive migration: legacy tokens/files remain untouched unless import succeeds
- Codex DB tokens are encrypted into vault and cleared from system_config only after successful import
- Antigravity files are imported only when sufficient fields (refresh_token) exist; otherwise untouched
- Mapping legacy provider IDs (gemini, codex, zen, etc.) to route-qualified IDs (oauth:..., direct:...)
- Normalizing hunter/verifier models and chat session models to blm:<route_id>/<upstream_model>
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_chat import ChatSession
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.models.system_config import SystemConfig
from app.services.provider_vault import ProviderVault, get_provider_vault
from app.services.route_registry import (
    map_legacy_model_to_route,
    normalize_legacy_provider_id,
    parse_route_model_id,
    provider_to_route_id,
    resolve_active_route_id,
)

logger = logging.getLogger("blm.legacy_migration")

# Legacy antigravity credentials path
if os.environ.get("DB_PATH"):
    LEGACY_AG_FILE = Path(os.environ["DB_PATH"]).parent / ".ag_credentials.json"
else:
    LEGACY_AG_FILE = Path(__file__).resolve().parents[3] / ".ag_credentials.json"


def _decode_jwt_account_id(token: str | None) -> str | None:
    """Best-effort extraction of account identity from a JWT for masked identity display."""
    if not token or not isinstance(token, str) or token.count(".") != 2:
        return None
    try:
        import base64

        payload_b64 = token.split(".")[1]
        rem = len(payload_b64) % 4
        if rem > 0:
            payload_b64 += "=" * (4 - rem)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
        auth = claims.get("https://api.openai.com/auth", {})
        return auth.get("chatgpt_account_id") or claims.get("email") or claims.get("sub")
    except Exception:
        return None


async def migrate_legacy_codex_tokens(vault: ProviderVault, session: AsyncSession) -> bool:
    """Import legacy Codex tokens into an encrypted OAuth credential before any new refresh.

    Old DB tokens in system_config are cleared ONLY after successful import into vault and DB.
    """
    res_acc = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "ai.codex_access_token")
    )
    access_token = res_acc.scalar_one_or_none()

    res_ref = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "ai.codex_refresh_token")
    )
    refresh_token = res_ref.scalar_one_or_none()

    if not access_token and not refresh_token:
        logger.debug("migrate_legacy_codex_tokens: no legacy tokens found")
        return False

    auth_data = {
        "access_token": (access_token or "").strip(),
        "refresh_token": (refresh_token or "").strip(),
    }

    # 1. Store in vault
    await vault.set_oauth_auth("codex", auth_data)

    # 2. Extract masked identity
    acct = _decode_jwt_account_id(access_token)
    masked = f"Codex ({acct[:8]}...)" if acct else "Codex User"

    # 3. Create or update AIProviderCredential
    cred_stmt = select(AIProviderCredential).where(
        AIProviderCredential.route_id == "oauth:codex",
        AIProviderCredential.kind == "oauth",
    )
    existing_cred = (await session.execute(cred_stmt)).scalar_one_or_none()

    if existing_cred is None:
        cred = AIProviderCredential(
            id=f"cred_codex_{secrets.token_hex(4)}",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="oauth_auth:codex",
            proxy_credential_name="codex.json",
            masked_identity=masked,
            priority=1,
            weight=1,
            enabled=True,
            status="active",
        )
        session.add(cred)
    else:
        existing_cred.vault_reference = "oauth_auth:codex"
        existing_cred.enabled = True
        existing_cred.status = "active"

    # 4. Clear old tokens ONLY after successful import
    await session.execute(
        delete(SystemConfig).where(
            SystemConfig.key.in_(["ai.codex_access_token", "ai.codex_refresh_token"])
        )
    )
    await session.commit()
    logger.info("migrate_legacy_codex_tokens: successfully imported legacy Codex tokens into vault")
    return True


async def migrate_legacy_antigravity_tokens(
    vault: ProviderVault,
    session: AsyncSession,
    creds_path: Path | None = None,
) -> tuple[bool, str]:
    """Attempt Antigravity import only with sufficient credential fields.

    Otherwise marks re-login required and leaves the old file untouched.
    """
    path = creds_path or LEGACY_AG_FILE
    if not path.exists():
        return False, "no_file"

    try:
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception as exc:
        logger.warning("migrate_legacy_antigravity_tokens: failed to read %s: %s", path, exc)
        return False, "relogin_required"

    if not isinstance(data, dict) or not data.get("refresh_token"):
        logger.warning(
            "migrate_legacy_antigravity_tokens: missing refresh_token; leaving file untouched"
        )
        return False, "relogin_required"

    # 1. Store in vault
    await vault.set_oauth_auth("antigravity", data)

    # 2. Identity display
    email = data.get("email") or "Google Account"
    masked = f"Antigravity ({email})"

    # 3. Create or update AIProviderCredential
    cred_stmt = select(AIProviderCredential).where(
        AIProviderCredential.route_id == "oauth:antigravity",
        AIProviderCredential.kind == "oauth",
    )
    existing_cred = (await session.execute(cred_stmt)).scalar_one_or_none()

    if existing_cred is None:
        cred = AIProviderCredential(
            id=f"cred_ag_{secrets.token_hex(4)}",
            route_id="oauth:antigravity",
            kind="oauth",
            vault_reference="oauth_auth:antigravity",
            proxy_credential_name="antigravity.json",
            masked_identity=masked,
            priority=1,
            weight=1,
            enabled=True,
            status="active",
        )
        session.add(cred)
    else:
        existing_cred.vault_reference = "oauth_auth:antigravity"
        existing_cred.enabled = True
        existing_cred.status = "active"

    await session.commit()

    # 4. Remove old file only after successful DB & vault commit
    try:
        path.unlink(missing_ok=True)
        logger.info("migrate_legacy_antigravity_tokens: imported and unlinked %s", path)
    except Exception as exc:
        logger.warning("migrate_legacy_antigravity_tokens: failed to unlink %s: %s", path, exc)

    return True, "imported"


async def migrate_legacy_providers_and_models(session: AsyncSession) -> None:
    """Normalize stored ai.provider, hunter/verifier models, and chat sessions to route-qualified format."""
    # 1. Resolve & normalize ai.provider if stored in DB (do NOT write a spurious row if absent)
    res_prov = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "ai.provider")
    )
    prov_row = res_prov.scalar_one_or_none()
    if prov_row and prov_row.value and prov_row.value.strip():
        norm_prov = provider_to_route_id(prov_row.value.strip())
        if prov_row.value != norm_prov:
            prov_row.value = norm_prov
            logger.info("migrate_legacy_providers_and_models: updated ai.provider to %s", norm_prov)

    # Use central resolution respecting DB value or falling back to settings.ai_provider
    active_route_id = await resolve_active_route_id(session)

    # 2. Normalize ai.hunter_model
    res_hunter = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "ai.hunter_model")
    )
    hunter_row = res_hunter.scalar_one_or_none()
    if hunter_row and hunter_row.value:
        norm_hunter = map_legacy_model_to_route(hunter_row.value, active_route_id)
        if hunter_row.value != norm_hunter:
            hunter_row.value = norm_hunter
            logger.info("migrate_legacy_providers_and_models: updated ai.hunter_model to %s", norm_hunter)

    # 3. Normalize ai.verifier_model
    res_verifier = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "ai.verifier_model")
    )
    verifier_row = res_verifier.scalar_one_or_none()
    if verifier_row and verifier_row.value:
        norm_verifier = map_legacy_model_to_route(verifier_row.value, active_route_id)
        if verifier_row.value != norm_verifier:
            verifier_row.value = norm_verifier
            logger.info("migrate_legacy_providers_and_models: updated ai.verifier_model to %s", norm_verifier)

    # 4. Normalize chat_sessions models
    res_sessions = await session.execute(select(ChatSession))
    sessions = res_sessions.scalars().all()
    for s in sessions:
        if s.model and not s.model.startswith("blm:"):
            norm_m = map_legacy_model_to_route(s.model, active_route_id)
            if s.model != norm_m:
                s.model = norm_m
                logger.debug("migrate_legacy_providers_and_models: updated session %s model to %s", s.id, norm_m)

    await session.commit()


async def run_all_legacy_migrations(vault: ProviderVault, session: AsyncSession) -> dict[str, Any]:
    """Execute all legacy migrations safely in sequence."""
    results = {}
    try:
        codex_migrated = await migrate_legacy_codex_tokens(vault, session)
        results["codex_migrated"] = codex_migrated
    except Exception as exc:
        await session.rollback()
        logger.error("run_all_legacy_migrations: codex migration error: %s", exc)
        results["codex_error"] = str(exc)

    try:
        ag_migrated, ag_reason = await migrate_legacy_antigravity_tokens(vault, session)
        results["antigravity_migrated"] = ag_migrated
        results["antigravity_reason"] = ag_reason
    except Exception as exc:
        await session.rollback()
        logger.error("run_all_legacy_migrations: antigravity migration error: %s", exc)
        results["antigravity_error"] = str(exc)

    try:
        await migrate_legacy_providers_and_models(session)
        results["models_migrated"] = True
    except Exception as exc:
        await session.rollback()
        logger.error("run_all_legacy_migrations: models migration error: %s", exc)
        results["models_error"] = str(exc)

    return results
