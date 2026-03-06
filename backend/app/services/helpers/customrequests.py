import time
from io import StringIO, BytesIO
import pandas as pd
import requests
from app.services.helpers.nse_history_cache import nse_history_cache

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}


def fetch_nse_historical_csv(symbol: str, from_date: str, to_date: str, csv: bool = True, session: requests.Session | None = None, headers: dict[str, str] | None = None, warmup: bool = True, use_cache: bool = True):
    """Fetch historical CSV from NSE and return a cleaned pandas DataFrame.
    Dates must be in DD-MM-YYYY format.

    Results are transparently cached in a local SQLite file (nse_history_cache.db).
    Ranges whose to_date is strictly before today are cached permanently; ranges
    that include today expire after ``nse_history_cache_ttl_hours`` hours.
    Pass use_cache=False to bypass cache entirely.
    """

    if headers is None:
        headers = HEADERS

    if use_cache:
        cached = nse_history_cache.get(symbol, from_date, to_date)
        if cached is not None:
            return cached

    url = f"https://www.nseindia.com/api/historicalOR/priceAndVolumeDataPerSecurity?symbol={symbol}&from={from_date}&to={to_date}&csv={'true' if csv else 'false'}"

    sess = session or requests.Session()
    sess.headers.update(headers)
    if warmup and session is None:
        try:
            sess.get("https://www.nseindia.com/", timeout=10)
        except Exception:
            pass
        time.sleep(0.8)

    resp = sess.get(url, timeout=20)
    resp.raise_for_status()

    try:
        df = pd.read_csv(BytesIO(resp.content), encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(StringIO(resp.text), encoding="utf-8-sig")

    # clean column names (remove BOM, surrounding quotes, extra spaces)
    df.columns = df.columns.str.lstrip('\ufeff').str.strip().str.replace('\"', '', regex=False)

    if use_cache:
        nse_history_cache.set(symbol, from_date, to_date, df)

    return df
