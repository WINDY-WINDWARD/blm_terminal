import sqlite3

try:
    conn = sqlite3.connect("data.db")
    conn.execute("DROP TABLE IF EXISTS users")
    conn.execute("DROP TABLE IF EXISTS _alembic_tmp_chat_sessions")
    conn.execute("DROP TABLE IF EXISTS _alembic_tmp_watchlists")
    conn.execute("DROP TABLE IF EXISTS _alembic_tmp_watchlist_items")
    conn.execute("DROP TABLE IF EXISTS _alembic_tmp_jobs")
    conn.commit()
    print("Dropped users table")
except Exception as e:
    print("Error:", e)
finally:
    conn.close()
