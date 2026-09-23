"""Tests for the NSE market-cap fill (job.market_caps).

Background: Analysis market caps aggregate per-member caps from
``StockUniverse.market_cap_cr`` first, but fresh installs have NULL caps
(NSE metadata often lacks tradeInfo, snapshot.market_cap was hardcoded
None). Re-triggering job.market_data only re-sums the same NULLs.

These tests pin:
- the tradeInfo parser edge cases,
- bounded fill with cursor resume (never clobbers existing caps),
- the market_data rebuild chain fires only when something was filled.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.stockuniverse import StockUniverse
from app.models.sync_state import SyncState
from app.services import data_sync as _ds_pkg  # noqa: F401  (package init side-effects)
from app.services.data_sync import market_caps as mc
from app.services.nse_client import SymbolNotFoundError
from app.services.nse_client_async import mcap_cr_from_trade_info


@pytest.fixture()
def memdb(monkeypatch: pytest.MonkeyPatch):
    engine = sa.create_engine("sqlite:///:memory:")
    StockUniverse.__table__.create(engine)
    SyncState.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    factory.engine = engine  # test-only handle for ad-hoc table setup

    class _Ctx:
        def __init__(self):
            self.session = factory()

        def __enter__(self):
            return self.session

        def __exit__(self, *exc):
            try:
                self.session.close()
            except Exception:
                pass
            return False

    monkeypatch.setattr(mc, "_SyncSessionLocal", _Ctx)
    return factory


def _add_universe(factory, symbols: dict[str, float | None]) -> None:
    session = factory()
    for sym, mcap in symbols.items():
        session.add(StockUniverse(symbol=sym, company_name=sym, segment="EQ",
                                  industry="Test Industry", ticker_failure_count=0,
                                  market_cap_cr=mcap))
    session.commit()
    session.close()


class FakeNSE:
    def __init__(self, caps: dict[str, float | None], missing: set[str] | None = None):
        self.caps = caps
        self.missing = missing or set()
        self.calls: list[str] = []

    def get_stock_metadata(self, symbol: str):
        self.calls.append(symbol)
        if symbol in self.missing:
            raise SymbolNotFoundError(symbol)
        return SimpleNamespace(symbol=symbol, market_cap_cr=self.caps.get(symbol))


class TestMcapParser:
    def test_rupees_to_cr(self):
        assert mcap_cr_from_trade_info({"totalMarketCap": 813988000000.0}) == pytest.approx(81398.8)

    def test_missing_block(self):
        assert mcap_cr_from_trade_info(None) is None
        assert mcap_cr_from_trade_info({}) is None

    def test_non_positive_never_clobbers(self):
        assert mcap_cr_from_trade_info({"totalMarketCap": 0}) is None
        assert mcap_cr_from_trade_info({"totalMarketCap": -5}) is None
        assert mcap_cr_from_trade_info({"totalMarketCap": "n/a"}) is None


class TestMarketCapsSync:
    def test_fills_nulls_never_clobbers(self, memdb, monkeypatch: pytest.MonkeyPatch):
        _add_universe(memdb, {"AAA": None, "BBB": 100.0, "CCC": None})
        monkeypatch.setattr(mc, "nse_client", FakeNSE({"AAA": 10.0, "BBB": 999.0, "CCC": None}))
        chained = []
        monkeypatch.setattr(mc, "_chain_market_rebuild", lambda: chained.append(1))

        out = mc._market_caps_sync(max_symbols=100)

        assert out == {"processed": 2, "filled": 1, "skipped": 1, "failed": 0}
        session = memdb()
        vals = dict(session.execute(sa.select(StockUniverse.symbol, StockUniverse.market_cap_cr)).all())
        session.close()
        assert vals == {"AAA": 10.0, "BBB": 100.0, "CCC": None}
        assert chained == [1]

    def test_bounded_with_cursor_resume(self, memdb, monkeypatch: pytest.MonkeyPatch):
        _add_universe(memdb, {"AAA": None, "BBB": None, "CCC": None})
        fake = FakeNSE({"AAA": 1.0, "BBB": 2.0, "CCC": 3.0})
        monkeypatch.setattr(mc, "nse_client", fake)
        monkeypatch.setattr(mc, "_chain_market_rebuild", lambda: None)
        monkeypatch.setattr(mc, "CURSOR_WRITE_EVERY", 1)

        out1 = mc._market_caps_sync(max_symbols=2)
        assert out1["filled"] == 2
        assert fake.calls == ["AAA", "BBB"]

        out2 = mc._market_caps_sync(max_symbols=2)
        assert out2["filled"] == 1
        assert fake.calls == ["AAA", "BBB", "CCC"]

    def test_unknown_symbol_skipped(self, memdb, monkeypatch: pytest.MonkeyPatch):
        _add_universe(memdb, {"AAA": None})
        monkeypatch.setattr(mc, "nse_client", FakeNSE({}, missing={"AAA"}))
        monkeypatch.setattr(mc, "_chain_market_rebuild", lambda: None)

        out = mc._market_caps_sync()
        assert out == {"processed": 1, "filled": 0, "skipped": 1, "failed": 0}

    def test_job_registered_with_caps_callable(self):
        from app.jobs.registry import JobRegistry
        from app.services.data_sync.market_caps import _market_caps_sync
        from app.workers.jobs import register_all_jobs

        register_all_jobs()
        job = JobRegistry.get("job.market_caps")
        assert job is not None
        assert job.callable is _market_caps_sync
        assert job.is_async is False

    def test_no_chain_when_nothing_filled(self, memdb, monkeypatch: pytest.MonkeyPatch):
        _add_universe(memdb, {"AAA": 5.0})
        monkeypatch.setattr(mc, "nse_client", FakeNSE({}))
        chained = []
        monkeypatch.setattr(mc, "_chain_market_rebuild", lambda: chained.append(1))

        out = mc._market_caps_sync()
        assert out["processed"] == 0
        assert chained == []

    def test_snapshot_mirror_updates_only(self, memdb, monkeypatch: pytest.MonkeyPatch):
        """Fills mirror into existing snapshot rows; never inserts stubs."""
        from datetime import date, datetime

        from app.models.ticker import TickerScreenerSnapshot

        TickerScreenerSnapshot.__table__.create(memdb.engine)
        _add_universe(memdb, {"AAA": None, "BBB": None})
        session = memdb()
        session.add(TickerScreenerSnapshot(
            symbol="AAA", last_date=date(2026, 1, 1), compute_date=date(2026, 1, 1),
            computed_at=datetime(2026, 1, 1), last_close=10.0, last_volume=100,
            last_open=9.0, last_high=11.0, last_low=8.0, market_cap=None))
        session.commit()
        session.close()
        monkeypatch.setattr(mc, "nse_client", FakeNSE({"AAA": 7.0, "BBB": 8.0}))
        monkeypatch.setattr(mc, "_chain_market_rebuild", lambda: None)

        out = mc._market_caps_sync(max_symbols=10)
        assert out["filled"] == 2
        session = memdb()
        rows = dict(session.execute(
            sa.select(TickerScreenerSnapshot.symbol, TickerScreenerSnapshot.market_cap)).all())
        session.close()
        # AAA updated in place; BBB untouched (no stub inserted).
        assert rows == {"AAA": 7.0}

    def test_time_cap_keeps_cursor(self, memdb, monkeypatch: pytest.MonkeyPatch):
        """A runtime-cap stop must resume, not restart (no wrap-around reset)."""
        _add_universe(memdb, {"AAA": None, "BBB": None, "CCC": None})
        monkeypatch.setattr(mc, "nse_client", FakeNSE({"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}))
        monkeypatch.setattr(mc, "_chain_market_rebuild", lambda: None)
        monkeypatch.setattr(mc, "MAX_RUN_SECONDS", -1)  # cap hit on first check

        out = mc._market_caps_sync(max_symbols=10)
        assert out["processed"] == 0
        # 3 candidates <= 10 => exhausted, but the cap fired first: the
        # wrap-around reset must be skipped so the next run resumes work.
        session = memdb()
        row = session.execute(sa.select(SyncState.last_symbol).where(
            SyncState.task_name == mc.TASK_NAME)).scalar_one_or_none()
        session.close()
        assert row is None

