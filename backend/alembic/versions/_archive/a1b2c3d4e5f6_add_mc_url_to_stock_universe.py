"""add_mc_url_to_stock_universe

Revision ID: a1b2c3d4e5f6
Revises: f1a3b7c92d4e
Create Date: 2026-03-14 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
import sqlalchemy.exc as sqla_exc

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f1a3b7c92d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col_if_not_exists(col_name: str, col_def: sa.Column) -> None:
    """Add a column only if it does not already exist (idempotent migration for SQLite)."""
    try:
        op.add_column("stock_universe", col_def)
    except sqla_exc.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            pass  # column already exists, safe to skip
        else:
            raise


def upgrade() -> None:
    _add_col_if_not_exists(
        "mc_url",
        sa.Column("mc_url", sa.String(512), nullable=True),
    )

    known_mc_urls = {
        "RELIANCE": "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI",
        "INFY": "https://www.moneycontrol.com/india/stockpricequote/computers-software/infosys/IT",
        "TCS": "https://www.moneycontrol.com/india/stockpricequote/computers-software/tataconsultancyservices/TCS",
        "HDFCBANK": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/hdfcbank/HDF01",
        "ICICIBANK": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/icicibank/ICI",
        "HINDUNILVR": "https://www.moneycontrol.com/india/stockpricequote/fmcg-personal-care/hindustanunilever/HLU",
        "ITC": "https://www.moneycontrol.com/india/stockpricequote/cigarettes/itc/ITC",
        "SBIN": "https://www.moneycontrol.com/india/stockpricequote/banks-public-sector/statebankindia/SBI",
        "BAJFINANCE": "https://www.moneycontrol.com/india/stockpricequote/finance-nbfc/bajajfinance/BAF",
        "MARUTI": "https://www.moneycontrol.com/india/stockpricequote/automobiles-maruti-suzuki/MSIL",
        "TATASTEEL": "https://www.moneycontrol.com/india/stockpricequote/metals-minerals/tatasteel/TS",
        "WIPRO": "https://www.moneycontrol.com/india/stockpricequote/computers-software/wipro/WRI",
    }

    for symbol, mc_url in known_mc_urls.items():
        op.execute(
            f"UPDATE stock_universe SET mc_url = '{mc_url}' WHERE symbol = '{symbol}'"
        )


def downgrade() -> None:
    op.drop_column("stock_universe", "mc_url")
