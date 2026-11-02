"""Tests for migration recovery and idempotency."""

import sqlite3
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

import main
from main import (
    _ALEMBIC_INI,
    _extract_revision_from_error,
    _get_current_revision,
    _run_migrations_sync,
)


def _set_db_version(db_path: str, version: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE alembic_version SET version_num = ?", (version,))
        conn.commit()
    finally:
        conn.close()


def test_extract_revision_from_error(tmp_path, monkeypatch):
    """Assert _extract_revision_from_error parses revision from path and returns None on unrelated errors."""
    db_file = tmp_path / "test_extract.db"
    monkeypatch.setattr(main.settings, "db_path", str(db_file))

    # Even if DB has a version, _extract_revision_from_error must never query or return it
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES ('k11111111111')")
    conn.commit()
    conn.close()

    assert _get_current_revision() == "k11111111111"

    # Windows path style
    win_err = r"OperationalError: duplicate column in alembic\versions\y11111111111a_add_market_category_returns.py line 20"
    assert _extract_revision_from_error(win_err) == "y11111111111a"

    # Posix path style
    posix_err = "OperationalError: duplicate column in alembic/versions/y11111111111a_add_market_category_returns.py line 20"
    assert _extract_revision_from_error(posix_err) == "y11111111111a"

    # Another revision (e.g. 31a1b2c3d4e5)
    iinvest_err = r"Error in alembic\versions\31a1b2c3d4e5_add_iinvest_columns_to_stock_universe.py"
    assert _extract_revision_from_error(iinvest_err) == "31a1b2c3d4e5"

    # Unrelated error must return None (and NOT current revision 'k11111111111')
    unrelated_exc = OperationalError("duplicate column name: return_1w", None, None)
    assert _extract_revision_from_error(unrelated_exc) is None
    assert _extract_revision_from_error("some unrelated error without version path") is None


def test_columns_present_version_behind(tmp_path, monkeypatch):
    """Scenario: DB schema is at head, but alembic_version lags behind (e.g. at k11111111111).

    _run_migrations_sync must succeed and bring alembic_version to head.
    """
    db_file = tmp_path / "test_lagging.db"
    monkeypatch.setattr(main.settings, "db_path", str(db_file))

    # Run migrations to head
    _run_migrations_sync()

    alembic_cfg = AlembicConfig(_ALEMBIC_INI)
    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_heads()[0]

    assert _get_current_revision() == head_rev

    # Rewind alembic_version to k11111111111 (before y11111111111a and z11111111111a)
    _set_db_version(str(db_file), "k11111111111")
    assert _get_current_revision() == "k11111111111"

    # Run migrations again. Because migrations are idempotent, it must succeed without error
    _run_migrations_sync()
    assert _get_current_revision() == head_rev


def test_db_from_newer_build_fails_fast_and_untouched(tmp_path, monkeypatch):
    """Scenario: DB is stamped with a revision unknown to this build.

    _run_migrations_sync must raise RuntimeError immediately and leave alembic_version intact.
    """
    db_file = tmp_path / "test_newer.db"
    monkeypatch.setattr(main.settings, "db_path", str(db_file))

    # Initialize to head
    _run_migrations_sync()

    # Stamp with unknown future revision
    unknown_rev = "zz99999999999a"
    _set_db_version(str(db_file), unknown_rev)
    assert _get_current_revision() == unknown_rev

    with pytest.raises(RuntimeError) as exc_info:
        _run_migrations_sync()

    assert f"unknown revision '{unknown_rev}'" in str(exc_info.value)
    assert "install the newer build or restore a database backup" in str(exc_info.value)

    # Version must remain untouched
    assert _get_current_revision() == unknown_rev


def test_duplicate_column_unattributable_revision_reraises(tmp_path, monkeypatch):
    """A duplicate-column error with an unattributable revision re-raises rather than stamping current revision."""
    db_file = tmp_path / "test_unattributable.db"
    monkeypatch.setattr(main.settings, "db_path", str(db_file))

    # Initialize DB
    _run_migrations_sync()
    _set_db_version(str(db_file), "k11111111111")
    assert _get_current_revision() == "k11111111111"

    stamped_revisions = []
    real_stamp = alembic_command.stamp

    def spy_stamp(cfg, rev):
        stamped_revisions.append(rev)
        return real_stamp(cfg, rev)

    monkeypatch.setattr(alembic_command, "stamp", spy_stamp)

    def mock_upgrade(cfg, rev):
        raise OperationalError("duplicate column: synthetic_col", None, None)

    monkeypatch.setattr(alembic_command, "upgrade", mock_upgrade)

    with pytest.raises(RuntimeError) as exc_info:
        _run_migrations_sync()

    assert "unrecoverable partial state" in str(exc_info.value)
    # Must NOT have stamped current revision
    assert "k11111111111" not in stamped_revisions
    assert len(stamped_revisions) == 0
    assert _get_current_revision() == "k11111111111"


def test_duplicate_column_recovery_stamps_failing_revision_and_retries(tmp_path, monkeypatch):
    """When duplicate column provides the failing revision, it stamps that revision and retries."""
    db_file = tmp_path / "test_recovery_advances.db"
    monkeypatch.setattr(main.settings, "db_path", str(db_file))

    _run_migrations_sync()
    _set_db_version(str(db_file), "k11111111111")

    stamped_revisions = []
    real_stamp = alembic_command.stamp

    def spy_stamp(cfg, rev):
        stamped_revisions.append(rev)
        return real_stamp(cfg, rev)

    monkeypatch.setattr(alembic_command, "stamp", spy_stamp)

    attempts = [0]
    real_upgrade = alembic_command.upgrade

    def failing_upgrade(cfg, rev):
        attempts[0] += 1
        if attempts[0] == 1:
            # Simulate a non-idempotent migration failure pointing to y11111111111a
            raise OperationalError(
                r"duplicate column name: return_1w in alembic\versions\y11111111111a_add_market_category_returns.py",
                None,
                None,
            )
        return real_upgrade(cfg, rev)

    monkeypatch.setattr(alembic_command, "upgrade", failing_upgrade)

    _run_migrations_sync()

    assert "y11111111111a" in stamped_revisions
    # Alembic version ended at head
    alembic_cfg = AlembicConfig(_ALEMBIC_INI)
    script = ScriptDirectory.from_config(alembic_cfg)
    assert _get_current_revision() == script.get_heads()[0]


def test_four_migrations_upgrade_idempotent(tmp_path, monkeypatch):
    """Calling upgrade() on each of the 4 modified migration files twice does not raise."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    db_file = tmp_path / "test_idempotent_ddl.db"
    monkeypatch.setattr(main.settings, "db_path", str(db_file))

    # Initialize schema to head
    _run_migrations_sync()

    alembic_cfg = AlembicConfig(_ALEMBIC_INI)
    script = ScriptDirectory.from_config(alembic_cfg)

    rev_ids = ["31a1b2c3d4e5", "31a1b2c3d4e6", "y11111111111a", "z11111111111a"]
    modules = [script.get_revision(rid).module for rid in rev_ids]

    engine = sa.create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            # Calling upgrade() a second time on all four modules must not raise duplicate column / index errors
            for mod in modules:
                mod.upgrade()
    engine.dispose()

