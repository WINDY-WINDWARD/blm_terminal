#!/usr/bin/env python3
r"""Extract browser cookies and save as pickle files for backend to consume.

This script is designed to run on Windows. It extracts cookies from browsers
and saves them as pickle files that can be loaded by the backend running in WSL.

Usage:
    python extract_cookies.py                    # Saves to ../cookies relative to script
    python extract_cookies.py --output D:\path   # Saves to specified directory
"""

from __future__ import annotations

import json
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICES = {
    "screener": {
        "domain": "screener.in",
        "browsers": ["chrome", "firefox"],
    },
    "morningstar": {
        "domain": "morningstar.in",
        "browsers": ["chrome", "firefox"],
    },
    "moneycontrol": {
        "domain": "moneycontrol.com",
        "browsers": ["firefox"],  # MC only uses Firefox
    },
}

STALE_HOURS = 12


def ensure_rookiepy() -> None:
    """Install rookiepy if not already installed."""
    try:
        import rookiepy  # type: ignore
    except ImportError:
        print("rookiepy not found, installing...")
        subprocess_check_call([sys.executable, "-m", "pip", "install", "rookiepy"])
        print("rookiepy installed successfully.")


def subprocess_check_call(args: list[str]) -> None:
    """Wrapper for subprocess.check_call."""
    import subprocess
    subprocess.check_call(args, stdout=sys.stdout, stderr=sys.stderr)


def extract_cookies_for_service(
    service_name: str, domain: str, browsers: list[str]
) -> dict[str, Any]:
    """Extract cookies for a service, trying multiple browsers.

    Returns:
        dict with keys: ok (bool), count (int), browser (str), cookies (list[dict])
    """
    import rookiepy  # type: ignore

    for browser in browsers:
        try:
            func = getattr(rookiepy, browser, None)
            if func is None:
                continue

            raw = func([domain])
            if raw:
                # Filter to only cookies for the target domain
                filtered = [
                    {"name": c.get("name"), "value": c.get("value"), "domain": c.get("domain")}
                    for c in raw
                    if c.get("domain") and domain in c.get("domain")
                ]
                if filtered:
                    return {
                        "ok": True,
                        "count": len(filtered),
                        "browser": browser,
                        "cookies": filtered,
                    }
        except Exception as e:
            print(f"  [{service_name}] Failed to read from {browser}: {e}", file=sys.stderr)
            continue

    return {"ok": False, "count": 0, "browser": None, "cookies": []}


def save_pickle(data: list[dict], path: Path) -> None:
    """Save cookies as pickle file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(data, f)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract browser cookies to pickle files.")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory for pickle files (default: ../cookies relative to script)",
    )
    args = parser.parse_args()

    # Resolve output directory
    script_dir = Path(__file__).resolve().parent
    if args.output:
        output_dir = Path(args.output).resolve()
    else:
        output_dir = script_dir.parent / "cookies"

    print(f"Output directory: {output_dir}")
    print(f"Extracting cookies for {len(SERVICES)} services...\n")

    # Ensure rookiepy is available
    ensure_rookiepy()

    results: dict[str, dict] = {}
    timestamp = datetime.now(timezone.utc).isoformat()

    for service_name, config in SERVICES.items():
        domain = config["domain"]
        browsers = config["browsers"]

        print(f"Extracting cookies for {service_name} ({domain})...")
        result = extract_cookies_for_service(service_name, domain, browsers)
        results[service_name] = {
            "ok": result["ok"],
            "count": result["count"],
            "browser": result["browser"],
        }

        if result["ok"]:
            pkl_path = output_dir / f"{service_name}.pkl"
            save_pickle(result["cookies"], pkl_path)
            print(f"  -> Saved {result['count']} cookies to {pkl_path.name}")
        else:
            print(f"  -> No cookies found (tried: {', '.join(browsers)})")

    # Save manifest
    manifest = {
        "generated_at": timestamp,
        "stale_after_hours": STALE_HOURS,
        "services": results,
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest saved to {manifest_path.name}")

    # Print summary
    print("\n=== Summary ===")
    for service_name, r in results.items():
        status = "OK" if r["ok"] else "FAILED"
        browser = f" ({r['browser']})" if r["browser"] else ""
        count = f" - {r['count']} cookies" if r["ok"] else ""
        print(f"  {service_name}: {status}{browser}{count}")


if __name__ == "__main__":
    main()