"""Cookie loader utility for loading pre-extracted cookies from pickle files.

Usage:
    cookies = load_cookies_from_pickle("screener")  # Returns list[dict] or None
"""

from __future__ import annotations

import logging
import os
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STALE_HOURS = 12

env_cookie_dir = os.environ.get("BLM_COOKIE_DIR", "")
if env_cookie_dir:
    COOKIE_PICKLE_DIR = Path(env_cookie_dir).resolve()
else:
    COOKIE_PICKLE_DIR = Path(__file__).resolve().parents[3] / "cookies"


def _get_manifest() -> dict[str, Any] | None:
    """Load manifest.json if it exists."""
    manifest_path = COOKIE_PICKLE_DIR / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        import json
        with open(manifest_path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to read manifest.json: %s", e)
        return None


def _is_stale(manifest: dict[str, Any]) -> bool:
    """Check if cookies are older than STALE_HOURS."""
    generated_at = manifest.get("generated_at")
    if not generated_at:
        return True

    try:
        generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - generated_time
        return age > timedelta(hours=STALE_HOURS)
    except Exception:
        return True


def load_cookies_from_pickle(service: str) -> list[dict[str, Any]] | None:
    """Load cookies for a given service from pickle file.

    Args:
        service: Service name (e.g., "screener", "morningstar", "moneycontrol")

    Returns:
        List of cookie dicts with keys: name, value, domain, or None if:
        - Pickle file doesn't exist
        - Manifest is stale (>12 hours old)
        - Pickle file is corrupt
        - COOKIE_PICKLE_DIR is not set and default path doesn't exist
    """
    if not COOKIE_PICKLE_DIR.exists():
        logger.debug("Cookie directory does not exist: %s", COOKIE_PICKLE_DIR)
        return None

    manifest = _get_manifest()
    if manifest and _is_stale(manifest):
        logger.warning(
            "Cookies are stale (generated %s, threshold %d hours)",
            manifest.get("generated_at"),
            STALE_HOURS,
        )

    pkl_path = COOKIE_PICKLE_DIR / f"{service}.pkl"
    if not pkl_path.exists():
        logger.debug("No pickle file found for service %s at %s", service, pkl_path)
        return None

    try:
        with open(pkl_path, "rb") as f:
            cookies = pickle.load(f)

        if not isinstance(cookies, list):
            logger.warning("Pickle file for %s is not a list", service)
            return None

        logger.info("Loaded %d cookies for %s from %s", len(cookies), service, pkl_path.name)
        return cookies  # type: ignore
    except Exception as e:
        logger.warning("Failed to load pickle for %s: %s", service, e)
        return None


def _extract_name_value(cookies: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten cookie list to ``{name: value}``."""
    out: dict[str, str] = {}
    for c in cookies:
        name = c.get("name")
        if name:
            out[name] = c.get("value", "")
    return out


def load_browser_cookies(
    service: str,
    domain: str,
    allowed_names: list[str] | None = None,
    browsers: tuple[str, ...] = ("chrome", "firefox"),
) -> dict[str, str]:
    """Load cookies for ``service`` from pickle if present."""
    # 1. Try pickle
    pickle_cookies = load_cookies_from_pickle(service)
    if pickle_cookies:
        extracted = _extract_name_value(pickle_cookies)
        if allowed_names is not None:
            extracted = {k: v for k, v in extracted.items() if k in allowed_names}
        if allowed_names is None or "sessionid" not in allowed_names or extracted.get("sessionid"):
            if extracted:
                logger.info("Using %s cookies from pickle file", service)
                return extracted

    logger.debug("No %s cookies found in any source", service)
    return {}