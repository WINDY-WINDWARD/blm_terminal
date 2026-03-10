"""
Fetch screener.in cookies from local browser profiles.

Validates the session cookie used by the backend ScreenerClient.

Usage:
    python scripts/fetch_screener_cookie.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class CookieResult:
    browser: str
    sessionid: str
    csrftoken: str
    sessionid_expires: int | None
    csrftoken_expires: int | None


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[0] + "***" + value[-1]
    return f"{value[:4]}***{value[-4:]}"


def _format_expiry(ts: int | None) -> str:
    if not ts:
        return "unknown"
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat()
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _extract_cookies(cookies: list[dict[str, Any]]) -> CookieResult | None:
    sessionid = ""
    csrftoken = ""
    sessionid_expires: int | None = None
    csrftoken_expires: int | None = None

    for cookie in cookies:
        name = cookie.get("name", "")
        if name == "sessionid":
            sessionid = cookie.get("value", "")
            sessionid_expires = cookie.get("expires")
        elif name == "csrftoken":
            csrftoken = cookie.get("value", "")
            csrftoken_expires = cookie.get("expires")

    if not sessionid:
        return None

    return CookieResult(
        browser="",
        sessionid=sessionid,
        csrftoken=csrftoken,
        sessionid_expires=sessionid_expires,
        csrftoken_expires=csrftoken_expires,
    )


def _fetch_from_browser(browser_name: str) -> CookieResult | None:
    try:
        import rookiepy
    except ImportError:
        print("rookiepy is not installed. Run: pip install rookiepy", file=sys.stderr)
        return None

    func = getattr(rookiepy, browser_name, None)
    if func is None:
        return None

    try:
        raw: list[dict[str, Any]] = func(["screener.in"])
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to read cookies from {browser_name}: {exc}", file=sys.stderr)
        return None

    if not raw:
        return None

    result = _extract_cookies(raw)
    if result is None:
        return None

    return CookieResult(
        browser=browser_name,
        sessionid=result.sessionid,
        csrftoken=result.csrftoken,
        sessionid_expires=result.sessionid_expires,
        csrftoken_expires=result.csrftoken_expires,
    )


def main() -> int:
    browsers = ["chrome", "firefox"]
    print("Checking screener.in cookies (Chrome -> Firefox)...")

    for browser in browsers:
        result = _fetch_from_browser(browser)
        if result is None:
            print(f"- {browser}: no sessionid cookie found")
            continue

        print(f"- {browser}: sessionid found")
        print(f"  sessionid: {_mask(result.sessionid)}")
        print(f"  sessionid_expires: {_format_expiry(result.sessionid_expires)}")
        if result.csrftoken:
            print(f"  csrftoken: {_mask(result.csrftoken)}")
            print(f"  csrftoken_expires: {_format_expiry(result.csrftoken_expires)}")
        else:
            print("  csrftoken: missing")

        print("\nStatus: OK (sessionid present).")
        return 0

    print(
        "\nStatus: MISSING sessionid. Log in at https://www.screener.in in Chrome "
        "or Firefox, then rerun this script."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
