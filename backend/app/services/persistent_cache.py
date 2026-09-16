"""Generic persistent JSON cache backed by the api_cache table."""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import AsyncSessionLocal
from app.models.api_cache import ApiCache

logger = logging.getLogger(__name__)

# Fast in-memory L1 cache to avoid hitting SQLite altogether on rapid repeated clicks
# { key: (parsed_data, expire_epoch) }
_L1_CACHE: dict[str, tuple[dict[str, Any], float]] = {}

async def get_cached_json(key: str) -> dict[str, Any] | None:
    """Retrieve parsed JSON from the persistent cache if not expired.
    Checks in-memory L1 first (<0.1ms), then SQLite api_cache table.
    """
    now_epoch = time.time()
    if key in _L1_CACHE:
        val, exp = _L1_CACHE[key]
        if now_epoch < exp:
            return val
        del _L1_CACHE[key]

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(ApiCache).where(ApiCache.key == key)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record:
                if record.expires_at > now:
                    try:
                        parsed = json.loads(record.payload)
                        _L1_CACHE[key] = (parsed, record.expires_at.replace(tzinfo=timezone.utc).timestamp())
                        return parsed
                    except json.JSONDecodeError:
                        pass

                # Expired or unparseable, clean up best-effort
                try:
                    del_stmt = delete(ApiCache).where(ApiCache.key == key)
                    await session.execute(del_stmt)
                    await session.commit()
                except Exception as del_err:
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    logger.debug("Failed to delete expired cache key %s: %s", key, del_err)
    except Exception as exc:
        logger.debug("Persistent cache read failed for key %s (falling back to live fetch): %s", key, exc)

    return None

async def set_cached_json(key: str, data: dict[str, Any], ttl_hours: int = 24) -> None:
    """Store JSON data in the persistent cache with a TTL.
    Never lets a DB lock or write error crash the caller.

    Writes are routed through the priority write queue for serialisation;
    the L1 in-memory cache is populated immediately so subsequent reads
    within the same process are instant (<0.1 ms).
    """
    now_epoch = time.time()
    expires_epoch = now_epoch + (ttl_hours * 3600)

    # Immediately populate L1 in-memory cache
    _L1_CACHE[key] = (data, expires_epoch)

    try:
        payload_str = json.dumps(data)
    except Exception as e:
        logger.warning("Failed to serialize cache data for key %s: %s", key, e)
        return

    # Convert epoch timestamps to naive UTC datetimes for SQLite
    from datetime import datetime, timezone
    created_at = datetime.fromtimestamp(now_epoch, tz=timezone.utc).replace(tzinfo=None)
    expires_at = datetime.fromtimestamp(expires_epoch, tz=timezone.utc).replace(tzinfo=None)

    try:
        from app.services.write_queue import enqueue_api_cache
        enqueue_api_cache(key, payload_str, created_at.timestamp(), expires_at.timestamp())
    except Exception as exc:
        logger.warning("Persistent cache enqueue failed for key %s: %s", key, exc)

