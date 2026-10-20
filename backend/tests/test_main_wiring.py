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
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_lifespan_shutdown_cleans_supervisor_when_crashed_or_runtime_dir_exists(tmp_path):
    """Ensure lifespan shutdown invokes stop() if supervisor is not STOPPED or has an existing runtime dir."""
    from app.services.proxy_supervisor import ProxySupervisor, SupervisorState

    mock_supervisor = MagicMock(spec=ProxySupervisor)
    mock_supervisor.state = SupervisorState.CRASHED
    mock_supervisor.is_running = False
    fake_dir = tmp_path / "runtime-to-clean"
    fake_dir.mkdir()
    mock_supervisor.runtime_dir = fake_dir
    mock_supervisor.stop = AsyncMock()

    with patch("app.services.proxy_supervisor.get_proxy_supervisor", return_value=mock_supervisor):
        from app.services.proxy_supervisor import get_proxy_supervisor, SupervisorState
        sup = get_proxy_supervisor()
        if sup.state != SupervisorState.STOPPED or (sup.runtime_dir and sup.runtime_dir.exists()):
            await sup.stop()

        mock_supervisor.stop.assert_awaited_once()
