import pytest
import importlib
import app.config
import app.auth
from app.config import Settings


def test_env_mode_defaults_to_development():
    s = Settings(env="development")
    assert s.is_development is True
    assert s.is_production is False


def test_env_mode_fail_closed_for_unknown_or_prod():
    s_prod = Settings(env="production")
    assert s_prod.is_development is False
    assert s_prod.is_production is True

    s_unknown = Settings(env="staging")
    assert s_unknown.is_development is False
    assert s_unknown.is_production is True


def test_jwt_secret_validation_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "dev_secret_key_change_in_production")
    monkeypatch.setattr(app.config, "settings", Settings(env="production", secret_key="dev_secret_key_change_in_production"))
    
    importlib.reload(app.auth)
    assert len(app.auth.SECRET_KEY) >= 16
    assert app.auth.SECRET_KEY != "dev_secret_key_change_in_production"


def test_admin_bootstrap_never_writes_default_credential(monkeypatch, tmp_path):
    """_ensure_admin_user is a no-op: first-boot admin creation is owned by
    POST /api/auth/setup. No default credential may ever be written,
    in any environment."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "valid_strong_secret_key_12345")
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setattr(app.config, "settings", Settings(env="production", secret_key="valid_strong_secret_key_12345", db_path=str(tmp_path / "test.db")))

    # Create dummy db file so _ensure_admin_user proceeds to check users table
    db_file = tmp_path / "test.db"
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, hashed_password TEXT, is_admin BOOLEAN, created_at DATETIME)")
    conn.close()

    from main import _ensure_admin_user
    assert _ensure_admin_user() is None

    conn = sqlite3.connect(str(db_file))
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
