"""In-process TTL caches for the BLM backend.

Uses cachetools.TTLCache (thread-safe, RLock internally).
Per-process — NOT shared across workers. For multi-worker deployments
rely on a shared cache in the upstream (e.g. OpenAlgo, NSE) or extend
this module with a shared backend.
"""

from __future__ import annotations

from cachetools import TTLCache as _TTLCache

nse_cache = _TTLCache(maxsize=200, ttl=600.0)
screener_html_cache = _TTLCache(maxsize=500, ttl=900.0)
screener_search_cache = _TTLCache(maxsize=200, ttl=60.0)
mcp_cache = _TTLCache(maxsize=200, ttl=600.0)
