"""Cookie loader utility for loading pickle files instead of calling rookiepy directly.

This module provides functions to load pre-extracted cookies from pickle files,
which is useful when the backend runs in WSL but cookies need to be extracted on Windows
(where rookiepy works due to DPAPI access).

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
    """Flatten a rookiepy-style cookie list to ``{name: value}``."""
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
    """Load cookies for ``service`` from pickle, falling back to rookiepy.

    The two-step strategy exists because:
      - The pickle path is fast (no browser DB lock), and works on every
        platform (notably WSL/Linux where rookiepy cannot read native
        browser DBs).
      - The rookiepy fallback is for development on macOS / native Linux
        where the user can grant access to Chrome/Firefox's encrypted
        cookie DB.

    Args:
        service: Pickle service name (``"screener"``, ``"morningstar"``,
            ``"moneycontrol"``).
        domain: Domain passed to ``rookiepy.<browser>([domain])`` when
            falling back to browser extraction.
        allowed_names: If set, only return cookies with these names
            (``{"sessionid", "csrftoken"}`` for screener).  If ``None``,
            return every cookie.
        browsers: Ordered tuple of browser names to try on fallback.
            Default ``("chrome", "firefox")``.

    Returns:
        ``{name: value}`` dict.  Empty if nothing was found.  Never
        raises — exceptions from rookiepy are logged and skipped so
        one broken browser does not poison the other.
    """
    # 1. Try pickle first
    pickle_cookies = load_cookies_from_pickle(service)
    if pickle_cookies:
        extracted = _extract_name_value(pickle_cookies)
        if allowed_names is not None:
            extracted = {k: v for k, v in extracted.items() if k in allowed_names}
        # screener requires a sessionid specifically; for other filters
        # we accept the dict as-is.
        if allowed_names is None or "sessionid" not in allowed_names or extracted.get("sessionid"):
            if extracted:
                logger.info("Using %s cookies from pickle file", service)
                return extracted
        logger.debug("Pickle for %s has no usable cookies, trying browsers", service)

    # 2. Fall back to browser extraction
    try:
        import rookiepy
    except ImportError:
        logger.debug("rookiepy not installed; cannot extract cookies from browser")
        return {}

    for browser_name in browsers:
        try:
            func = getattr(rookiepy, browser_name, None)
            if func is None:
                continue
            raw: list[dict[str, Any]] = func([domain])
            if not raw:
                continue
            cookies = _extract_name_value(raw)
            if allowed_names is not None:
                cookies = {k: v for k, v in cookies.items() if k in allowed_names}
            if cookies:
                logger.info("Found %s cookies in %s", service, browser_name)
                return cookies
            logger.debug(
                "No %s cookies in %s (after filter), trying next browser",
                service, browser_name,
            )
        except Exception as exc:
            logger.debug("Failed to read cookies from %s: %s", browser_name, exc)
            continue

    logger.debug("No %s cookies found in any source", service)
    return {}