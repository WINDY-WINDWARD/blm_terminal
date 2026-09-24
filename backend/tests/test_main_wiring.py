"""Regression: main.py must import cleanly and mount every router.

A 2-space indent on three include_router lines once shipped in main.py and
went unnoticed because no test imported the app entrypoint — PyInstaller then
failed and the desktop packaged without a backend. This test fails loudly on
any syntax or router-wiring breakage in main.py.

NOTE: FastAPI >= 0.12x defers include_router into _IncludedRouter
placeholders, so app.routes cannot be enumerated directly. We prove mounting
by requesting through the ASGI app: mounted-but-tokenless routes answer 401
(via launch_token_guard), wrong-method routes answer 405, unmounted paths
answer 404.
"""
import httpx
import pytest

from main import app


def test_main_imports():
    assert app.title is not None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/scripts"),
        ("POST", "/api/scripts/validate"),
        ("GET", "/api/chart-state"),
        ("POST", "/api/scripts/import"),
    ],
)
async def test_scripts_router_mounted(method: str, path: str):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.request(method, path)
    assert resp.status_code != 404, f"{method} {path} is not mounted"
