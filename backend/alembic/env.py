from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool, inspect

from alembic import context

# ---------------------------------------------------------------------------
# Make sure the backend package is importable from this file's directory.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import models so their tables are registered on Base.metadata.
from app.database import Base  # noqa: E402
from app.models import corporatefilings  # noqa: F401, E402
from app.models import stockuniverse  # noqa: F401, E402
from app.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object.
# ---------------------------------------------------------------------------
config = context.config

# Set the DB URL from the app settings so .env overrides are respected.
# Uses the plain sqlite:// (sync) driver — Alembic doesn't need aiosqlite.
config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Shared context options applied to both offline and online modes.
_CONTEXT_OPTS: dict = {
    "target_metadata": target_metadata,
    "render_as_batch": True,   # required for SQLite column alterations
    "compare_type": True,      # detect column type/nullability changes
}


# ---------------------------------------------------------------------------
# Offline mode: emit SQL to stdout without a live connection.
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_CONTEXT_OPTS,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode: connect to a live DB and apply migrations.
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, **_CONTEXT_OPTS)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
