#!/usr/bin/env python3
"""
API Response Documentation Script

Fetches and prints the response structure for all BLM Analytics API endpoints.

Usage:
    python docs/api_responses.py

Environment:
    BLM_BASE_URL    Base URL (default: http://127.0.0.1:8000)

Output:
    Writes to docs/API_RESPONSES.md
"""

import json
import os
import sys
from pathlib import Path

BASE_URL = os.environ.get("BLM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUTPUT_FILE = Path(__file__).parent / "API_RESPONSES.md"


class OutputWriter:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.lines: list[str] = []

    def write(self, *args, **kwargs):
        text = " ".join(str(a) for a in args)
        self.lines.append(text)

    def print_section(self, title: str) -> None:
        self.write("")
        self.write("=" * 60)
        self.write(f"  {title}")
        self.write("=" * 60)

    def print_json(self, data: object, indent: int = 2) -> None:
        self.write(json.dumps(data, indent=indent, default=str))

    def save(self):
        self.filepath.write_text("\n".join(self.lines))


out = OutputWriter(OUTPUT_FILE)


def get(path: str) -> tuple[int, str | object]:
    import requests

    try:
        resp = requests.get(f"{BASE_URL}{path}", timeout=60)
        status = resp.status_code
        if status == 200:
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = resp.json()
                except json.JSONDecodeError:
                    body = resp.text
            else:
                body = resp.text
        elif status == 404:
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = resp.json()
                except json.JSONDecodeError:
                    body = resp.text
            else:
                body = resp.text
        elif status >= 500:
            body = {"_error": "Upstream error", "_status": status}
        else:
            body = resp.text
        return status, body
    except Exception as e:
        return 0, {"_error": str(e)}


def main():
    out.write("BLM Analytics API Documentation")
    out.write(f"Base URL: {BASE_URL}")
    out.write(f"Generated: {__file__}")

    # Health check
    out.print_section("GET /health")
    status, body = get("/health")
    out.write(f"Status: {status}")
    out.print_json(body)

    # Stock Universe
    out.print_section("GET /api/stockuniverse")
    status, body = get("/api/stockuniverse")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.write(f"Response: {body}")

    out.print_section("GET /api/stockuniverse/{symbol}")
    status, body = get("/api/stockuniverse/RELIANCE")
    out.write(f"Status: {status}")
    out.print_json(body)

    out.print_section("GET /api/stockuniverse/search/{prefix}")
    status, body = get("/api/stockuniverse/search/REL")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.write(f"Response: {body}")

    # Corporate Filings
    out.print_section("GET /api/corporatefilings/{symbol}")
    status, body = get("/api/corporatefilings/RELIANCE")
    out.write(f"Status: {status}")
    if status == 200 and isinstance(body, str):
        out.write(f"Response: CSV text ({len(body)} chars)")
        out.write("")
        out.write("Full CSV content:")
        out.write("```")
        out.write(body)
        out.write("```")
    else:
        out.print_json(body)

    # Market - Top Gainers
    out.print_section("GET /api/market/top-gainers")
    status, body = get("/api/market/top-gainers")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.print_json(body)

    # Market - Top Losers
    out.print_section("GET /api/market/top-losers")
    status, body = get("/api/market/top-losers")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.print_json(body)

    # Market - Bulk Deals
    out.print_section("GET /api/market/bulk-deals/{symbol}")
    status, body = get("/api/market/bulk-deals/RELIANCE")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.print_json(body)

    # Market - Block Deals
    out.print_section("GET /api/market/block-deals/{symbol}")
    status, body = get("/api/market/block-deals/RELIANCE")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.print_json(body)

    # Market - High Short Interest
    out.print_section("GET /api/market/high-short-interest")
    status, body = get("/api/market/high-short-interest")
    out.write(f"Status: {status}")
    if isinstance(body, list):
        out.write(f"Response: List of {len(body)} items")
        if body:
            out.write("Sample item (first):")
            out.print_json(body[0])
    else:
        out.print_json(body)

    # Market - Change Ranges
    out.print_section("GET /api/market/change-ranges/{symbol}")
    status, body = get("/api/market/change-ranges/RELIANCE")
    out.write(f"Status: {status}")
    out.print_json(body)

    # Market - Symbol Data
    out.print_section("GET /api/market/symbol-data/{symbol}")
    status, body = get("/api/market/symbol-data/RELIANCE")
    out.write(f"Status: {status}")
    out.print_json(body)

    out.print_section("END OF DOCUMENTATION")

    out.save()
    print(f"Documentation written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
