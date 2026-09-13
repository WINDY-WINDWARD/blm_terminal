import tempfile
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

def test_stock_universe_seeding():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        conn = sqlite3.connect(tmp_path)
        prod = sqlite3.connect('backend/data.db')
        cur = prod.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_universe'")
        schema = cur.fetchone()[0]
        conn.execute(schema)
        conn.commit()
        prod.close()
        conn.close()

        sys.path.insert(0, 'backend')
        from app.config import settings
        with patch.object(settings, 'db_path', tmp_path):
            from main import _ensure_stock_universe
            _ensure_stock_universe()

        conn = sqlite3.connect(tmp_path)
        count = conn.execute('SELECT COUNT(*) FROM stock_universe').fetchone()[0]
        sample = conn.execute('SELECT symbol, company_name, series FROM stock_universe LIMIT 3').fetchall()
        conn.close()

        print(f'Verification success: {count} stocks seeded into empty database.')
        print(f'Sample stocks: {sample}')
        assert count > 2000, f'Expected > 2000, got {count}'

        # Test idempotency: running it a second time should not crash or duplicate
        with patch.object(settings, 'db_path', tmp_path):
            _ensure_stock_universe()

        conn = sqlite3.connect(tmp_path)
        count2 = conn.execute('SELECT COUNT(*) FROM stock_universe').fetchone()[0]
        conn.close()
        assert count2 == count, f'Count changed from {count} to {count2}'
        print('Idempotency verified: re-running did not change count.')

        # Verify search/prefix query behavior (used by autocomplete endpoints)
        conn = sqlite3.connect(tmp_path)
        tcs_matches = conn.execute("SELECT symbol, company_name FROM stock_universe WHERE symbol LIKE 'TCS%'").fetchall()
        conn.close()
        assert len(tcs_matches) >= 1, "Expected autocomplete prefix match for 'TCS'"
        assert any(row[0] == 'TCS' for row in tcs_matches), "Expected 'TCS' in matches"
        print(f"Autocomplete check verified: 'TCS' prefix found: {tcs_matches}")

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

if __name__ == '__main__':
    test_stock_universe_seeding()
