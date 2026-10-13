import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.routers.ai_chat import (
    FALLBACK_ZEN_MODELS,
    _AISTUDIO_RETIRED_PREFIXES,
    get_chat_models,
    get_provider_models,
    normalize_gemini_model_id,
)
from app.routers.system_config import normalize_gemini_worker_model


@pytest.mark.asyncio
async def test_gemini_provider_models():
    """Verify that get_provider_models for gemini returns exclusively 3.8 Flash tiers with Medium first."""
    models = await get_provider_models("gemini")
    assert len(models) == 3

    expected_ids = [
        "gemini-3.8-flash-medium",
        "gemini-3.8-flash-low",
        "gemini-3.8-flash-high",
    ]
    assert [m["id"] for m in models] == expected_ids
    assert models[0]["id"] == "gemini-3.8-flash-medium"

    for m in models:
        assert "3.1" not in m["id"]
        assert "3.7" not in m["id"]
        assert "3.5" not in m["id"]
        assert "pro" not in m["id"].lower()
        assert "3.8-flash" in m["id"]


@pytest.mark.asyncio
async def test_gemini_chat_models():
    """Verify that get_chat_models returns the 3.8 Flash tiers when provider is gemini."""
    with patch("app.routers.ai_chat.get_dynamic_ai_provider", AsyncMock(return_value="gemini")):
        models = await get_chat_models()
        assert len(models) == 3
        assert [m["id"] for m in models] == [
            "gemini-3.8-flash-medium",
            "gemini-3.8-flash-low",
            "gemini-3.8-flash-high",
        ]


def test_zen_and_aistudio_fallback_catalog():
    """Verify sub-3.8 models are retired from Zen fallbacks and AI Studio filter."""
    zen_ids = [m["id"] for m in FALLBACK_ZEN_MODELS]
    assert "gemini-3.8-flash" in zen_ids
    assert "gemini-3.7-flash" not in zen_ids
    assert "gemini-3.5-flash" not in zen_ids

    assert "gemini-3.1-pro" in _AISTUDIO_RETIRED_PREFIXES
    assert "gemini-3.7-flash" in _AISTUDIO_RETIRED_PREFIXES
    assert "gemini-3.5-flash" in _AISTUDIO_RETIRED_PREFIXES


def test_normalize_gemini_model_id():
    """Verify normalization of various Gemini model identifiers."""
    assert normalize_gemini_model_id("gemini-3.1-pro-high") == "gemini-3.8-flash-high"
    assert normalize_gemini_model_id("gemini-3.7-flash-high") == "gemini-3.8-flash-high"
    assert normalize_gemini_model_id("gemini-3.7-flash-medium") == "gemini-3.8-flash-medium"
    assert normalize_gemini_model_id("gemini-3.7-flash-low") == "gemini-3.8-flash-low"
    assert normalize_gemini_model_id("gemini-3.1-pro") == "gemini-3.8-flash-low"
    assert normalize_gemini_model_id("gemini-3.8-flash-low") == "gemini-3.8-flash-low"
    assert normalize_gemini_model_id("gemini-3.8-flash-medium") == "gemini-3.8-flash-medium"
    assert normalize_gemini_model_id("gemini-3.8-flash-high") == "gemini-3.8-flash-high"
    assert normalize_gemini_model_id("gemini-3.8-flash") == "gemini-3.8-flash-medium"
    assert normalize_gemini_model_id("gemini") == "gemini-3.8-flash-low"
    # Non-gemini models must remain unchanged
    assert normalize_gemini_model_id("claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert normalize_gemini_model_id("gpt-5.4-mini") == "gpt-5.4-mini"


def test_normalize_gemini_worker_model():
    """Verify worker model normalization with default tiers."""
    assert normalize_gemini_worker_model("gemini-3.1-pro", default_tier="high") == "gemini-3.8-flash-high"
    assert normalize_gemini_worker_model("gemini-3.1-pro", default_tier="low") == "gemini-3.8-flash-low"
    assert normalize_gemini_worker_model("gemini", default_tier="high") == "gemini-3.8-flash-high"
    assert normalize_gemini_worker_model("gemini-3.7-flash-high") == "gemini-3.8-flash-high"
    assert normalize_gemini_worker_model("gemini-3.7-flash-medium") == "gemini-3.8-flash-medium"
    assert normalize_gemini_worker_model("gemini-3.7-flash-low") == "gemini-3.8-flash-low"
    assert normalize_gemini_worker_model("kimi-k2.6") == "kimi-k2.6"


def test_migrate_deprecated_gemini_models_db():
    """Verify the database migration logic against sample SQLite tables."""
    db_file = Path(__file__).parent / "test_migration_gemini.db"
    if db_file.exists():
        db_file.unlink()

    try:
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()

        cur.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY, model TEXT)")

        cur.execute("INSERT INTO system_config VALUES ('ai.hunter_model', 'gemini-3.1-pro-high')")
        cur.execute("INSERT INTO system_config VALUES ('ai.verifier_model', 'gemini-3.7-flash-low')")

        cur.execute("INSERT INTO chat_sessions VALUES (1, 'gemini-3.1-pro')")
        cur.execute("INSERT INTO chat_sessions VALUES (2, 'gemini-3.7-flash-high')")
        cur.execute("INSERT INTO chat_sessions VALUES (3, 'gemini-3.7-flash-medium')")
        cur.execute("INSERT INTO chat_sessions VALUES (5, 'gemini')")
        cur.execute("INSERT INTO chat_sessions VALUES (4, 'claude-sonnet-4-6')")
        conn.commit()
        conn.close()

        with patch("main.settings.db_path", str(db_file)):
            from main import _migrate_deprecated_gemini_models
            _migrate_deprecated_gemini_models()

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()

        hunter = cur.execute("SELECT value FROM system_config WHERE key = 'ai.hunter_model'").fetchone()[0]
        verifier = cur.execute("SELECT value FROM system_config WHERE key = 'ai.verifier_model'").fetchone()[0]
        assert hunter == "gemini-3.8-flash-high"
        assert verifier == "gemini-3.8-flash-low"

        sessions = dict(cur.execute("SELECT id, model FROM chat_sessions").fetchall())
        assert sessions[1] == "gemini-3.8-flash-low"
        assert sessions[2] == "gemini-3.8-flash-high"
        assert sessions[3] == "gemini-3.8-flash-medium"
        assert sessions[5] == "gemini-3.8-flash-low"
        assert sessions[4] == "claude-sonnet-4-6"

        conn.close()
    finally:
        if db_file.exists():
            db_file.unlink()
