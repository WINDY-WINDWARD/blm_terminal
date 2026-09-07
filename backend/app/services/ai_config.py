"""Helper functions for dynamic AI configuration."""

import logging
from typing import Optional

from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)

async def get_dynamic_ai_provider() -> str:
    """Fetch AI Provider from settings or fallback to dynamic system_config.
    
    Returns 'zen', 'go', or 'gemini' (or 'antigravity').
    """
    provider = settings.ai_provider
    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "ai.provider")
            )
            db_val = res.scalar_one_or_none()
            if db_val and db_val.strip():
                provider = db_val.strip().lower()
    except Exception as e:
        logger.warning("Failed to read ai.provider from db: %s", e)
    
    # Normalize legacy antigravity to gemini
    if provider == "antigravity":
        provider = "gemini"
        
    return provider

async def get_dynamic_ai_api_key(provider: str) -> str:
    """Fetch the correct API key based on the dynamically selected provider."""
    # Start with default environment variables based on provider
    api_key = settings.ai_api_key
    if provider == "zen":
        api_key = settings.opencode_zen_api_key
        
    # Override with database values if present
    db_key = f"ai.{provider}_api_key" if provider in ("zen", "go") else "ai.api_key"
    
    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == db_key)
            )
            db_val = res.scalar_one_or_none()
            if db_val and db_val.strip():
                api_key = db_val.strip()
    except Exception as e:
        logger.warning("Failed to read %s from db: %s", db_key, e)
        
    return api_key
