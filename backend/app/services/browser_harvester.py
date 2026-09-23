"""On-Demand Browser Harvester Service.

Provides anonymous, consent-gated browser automation using Playwright/Camoufox.
Binaries are NOT bundled in the initial installer; they are prepared/downloaded
on-demand in the background ONLY after user consent.

Features:
- Global asyncio.Lock to prevent spawning multiple concurrent browser instances
- 24-hour persistent SQLite/memory caching for tokens and DOM HTML
- harvest_local_storage(url, key)
- harvest_public_html(url, selector)
"""

import asyncio
import concurrent.futures
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import AsyncSessionLocal
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# Global lock to serialize browser invocations and avoid resource exhaustion
_BROWSER_LOCK = asyncio.Lock()

# In-memory fast cache with TTL (epoch timestamp)
# { cache_key: (value, expire_timestamp) }
_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}

# Background download task handle
_DOWNLOAD_TASK: asyncio.Task | None = None
_BINARY_CHECKED = False

# ── Browser provisioning state (provision-on-consent) ────────────────────────
# A client machine has no Camoufox browser until it is fetched on demand.
# States: "unknown" | "ready" | "missing" | "downloading" | "failed"
_BROWSER_STATUS: dict[str, Any] = {
    "state": "unknown",
    "downloaded": 0,
    "total": 0,
    "version": None,
    "error": None,
    "updated_at": 0.0,
}
_STATUS_LOCK = threading.Lock()
_FETCH_THREAD: threading.Thread | None = None
_AUTO_FETCH_DONE = False


def _set_browser_status(
    state: str,
    *,
    downloaded: int = 0,
    total: int = 0,
    version: str | None = None,
    error: str | None = None,
) -> None:
    with _STATUS_LOCK:
        _BROWSER_STATUS["state"] = state
        _BROWSER_STATUS["downloaded"] = downloaded
        _BROWSER_STATUS["total"] = total
        if version is not None:
            _BROWSER_STATUS["version"] = version
        _BROWSER_STATUS["error"] = error
        _BROWSER_STATUS["updated_at"] = time.time()


def _installed_browser_present() -> str | None:
    """Return the active Camoufox browser path, or None if none is installed."""
    try:
        from camoufox.multiversion import get_active_path

        p = get_active_path()
        return str(p) if p else None
    except Exception:
        return None


def get_browser_status() -> dict[str, Any]:
    """Live browser provisioning status (safe to call from any thread)."""
    with _STATUS_LOCK:
        snapshot = dict(_BROWSER_STATUS)
    present = _installed_browser_present()
    # Reconcile stored state with ground truth so externally provisioned
    # browsers (dev machines, manual `camoufox fetch`) report correctly.
    if present and snapshot["state"] in ("unknown", "missing", "failed"):
        snapshot["state"] = "ready"
        snapshot["error"] = None
    elif not present and snapshot["state"] == "ready":
        snapshot["state"] = "missing"
    return snapshot


# ── Cross-process fetch lock ─────────────────────────────────────────────────
# Two backend processes (the known double-spawn) must not download ~1GB each
# into the same INSTALL_DIR. Exclusive-create gives us an atomic mutex.
_FETCH_LOCK_NAME = ".fetch.lock"
_STALE_LOCK_MAX_AGE = 2 * 3600


def _fetch_lock_path() -> Path | None:
    try:
        from camoufox.pkgman import INSTALL_DIR

        return Path(INSTALL_DIR) / _FETCH_LOCK_NAME
    except Exception:
        pass
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "camoufox" / _FETCH_LOCK_NAME
    except Exception:
        return None


def _holder_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _acquire_fetch_lock() -> int | None:
    """Atomically claim the cross-process fetch lock.

    Returns an os fd (>= 0, must be passed to _release_fetch_lock), -1 to
    proceed without a lock (no lock dir available), or None when another
    live process already holds it.
    """
    path = _fetch_lock_path()
    if path is None:
        return -1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return -1
    for _ in range(2):  # one retry after clearing a stale lock
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()}:{time.time():.0f}".encode())
            except Exception:
                pass
            return fd
        except FileExistsError:
            pass
        except Exception:
            return -1
        # Lock exists: take over only if the holder is dead or ancient.
        try:
            pid_s, _, ts_s = path.read_text().strip().partition(":")
            pid, ts = int(pid_s), float(ts_s)
            if _holder_alive(pid) and (time.time() - ts <= _STALE_LOCK_MAX_AGE):
                return None
        except Exception:
            return None
        try:
            path.unlink()
        except Exception:
            return None
    return None


def _release_fetch_lock(fd: int | None) -> None:
    if fd is None or fd < 0:
        return
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        path = _fetch_lock_path()
        if path is not None:
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _fetch_worker() -> None:
    """Thread body: claim the cross-process lock, then fetch."""
    lock_fd = _acquire_fetch_lock()
    if lock_fd is None:
        logger.info("BrowserProvision: fetch already running in another process; skipping")
        _set_browser_status("downloading")
        return
    try:
        _fetch_worker_locked()
    finally:
        _release_fetch_lock(lock_fd)


def _fetch_worker_locked() -> None:
    """Thread body: download + install the Camoufox browser, then warm it."""
    global _BINARY_CHECKED
    _set_browser_status("downloading")

    def _progress(downloaded: int, total: int) -> None:
        _set_browser_status("downloading", downloaded=downloaded, total=total)

    try:
        from camoufox.pkgman import CamoufoxFetcher, webdl

        try:

            class _ProgressFetcher(CamoufoxFetcher):  # type: ignore
                @staticmethod
                def download_file(file: Any, url: str) -> Any:
                    return webdl(url, buffer=file, bar=False, progress_callback=_progress)

            fetcher: Any = _ProgressFetcher()
        except Exception:
            # Fall back to the stock fetcher (rich bars go to the backend log).
            fetcher = CamoufoxFetcher()
        try:
            verstr = fetcher.verstr
        except Exception:
            verstr = None
        logger.info("BrowserProvision: fetching Camoufox browser%s...", f" v{verstr}" if verstr else "")
        fetcher.install()
        present = _installed_browser_present()
        if present:
            _BINARY_CHECKED = True
            _set_browser_status("ready", version=verstr)
            logger.info("BrowserProvision: Camoufox browser ready (%s)", present)
            try:
                ensure_warm_browser()
            except Exception as exc:
                logger.debug("BrowserProvision: warm start after fetch failed: %s", exc)
        else:
            _set_browser_status("failed", error="fetch completed but no active browser found")
            logger.error("BrowserProvision: fetch completed but no active browser found")
    except Exception as exc:
        _set_browser_status("failed", error=str(exc)[:300])
        logger.error("BrowserProvision: browser fetch failed: %s", exc)


def trigger_browser_fetch(manual: bool = False) -> dict[str, Any]:
    """Start a background Camoufox browser fetch unless already present/running.

    Safe to call liberally: no-ops when a browser is installed, a fetch is
    already running, or the one-shot auto-fetch already fired (manual retries
    bypass the one-shot guard).
    """
    global _FETCH_THREAD, _AUTO_FETCH_DONE
    with _STATUS_LOCK:
        if _BROWSER_STATUS["state"] == "downloading":
            return dict(_BROWSER_STATUS)
    if _installed_browser_present():
        _set_browser_status("ready")
        return get_browser_status()
    with _STATUS_LOCK:
        if _AUTO_FETCH_DONE and not manual:
            return dict(_BROWSER_STATUS)
        _AUTO_FETCH_DONE = True
        t = _FETCH_THREAD
    if t is not None and t.is_alive():
        return get_browser_status()
    _set_browser_status("downloading")
    _FETCH_THREAD = threading.Thread(target=_fetch_worker, daemon=True, name="camoufox-fetch")
    _FETCH_THREAD.start()
    logger.info("BrowserProvision: browser fetch started (manual=%s)", manual)
    return get_browser_status()

# ── Persistent warm browser (speed-first: keep one headless browser alive
# for the whole app lifetime so harvests skip the 8-12s cold launch) ─────────
# The sync Camoufox/Playwright API is blocking, so the browser lives on a
# dedicated daemon thread. Async callers submit jobs via _WARM_QUEUE and await
# the Future without blocking the event loop.
_WARM_QUEUE: queue.Queue | None = None
_WARM_THREAD: threading.Thread | None = None
_WARM_READY = threading.Event()
_WARM_STOP = threading.Event()
_WARM_THREAD_LOCK = threading.Lock()
_WARM_PREWARM_URL = "https://iinvest.cogencis.com/"
_WARM_JOB_TIMEOUT = 45.0


def _get_cache_key(prefix: str, url: str, extra: str = "") -> str:
    return f"{prefix}:{url}:{extra}".strip(":")


_CONSENT_CACHE_TTL = 60
_consent_cache_val: bool | None = None
_consent_cache_time: float = 0.0


def invalidate_consent_cache() -> None:
    """Invalidate in-memory consent cache so state changes take effect immediately."""
    global _consent_cache_val, _consent_cache_time
    _consent_cache_val = None
    _consent_cache_time = 0.0


async def get_consent_status() -> bool:
    """Check if the user has given legal consent for advanced web extraction."""
    global _consent_cache_val, _consent_cache_time
    import time
    now = time.time()
    if _consent_cache_val is not None and now - _consent_cache_time < _CONSENT_CACHE_TTL:
        return _consent_cache_val

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(SystemConfig.value).where(SystemConfig.key == "scraping.advanced_consent")
            res = await session.execute(stmt)
            val = res.scalar_one_or_none()
            _consent_cache_val = (val == "true")
            _consent_cache_time = now
            return _consent_cache_val
    except Exception as e:
        logger.warning("BrowserHarvester: could not read consent status: %s", e)
        return False


async def get_cached_item(cache_key: str) -> Any | None:
    """Retrieve item from memory or SQLite system_config if not expired."""
    now = time.time()
    # 1. Check in-memory cache
    if cache_key in _MEMORY_CACHE:
        val, expires = _MEMORY_CACHE[cache_key]
        if now < expires:
            return val
        del _MEMORY_CACHE[cache_key]

    # 2. Check SQLite cache
    db_key = f"cache.harvester.{cache_key}"
    db_exp_key = f"cache.harvester_exp.{cache_key}"
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(SystemConfig.key, SystemConfig.value).where(
                SystemConfig.key.in_([db_key, db_exp_key])
            )
            res = await session.execute(stmt)
            rows = dict(res.fetchall())
            val = rows.get(db_key)
            exp_str = rows.get(db_exp_key)
            if val is not None and exp_str is not None:
                exp_val = float(exp_str)
                if now < exp_val:
                    _MEMORY_CACHE[cache_key] = (val, exp_val)
                    return val
    except Exception as e:
        logger.debug("BrowserHarvester cache lookup error: %s", e)

    return None


async def set_cached_item(cache_key: str, value: Any, ttl_seconds: int = 86400) -> None:
    """Store item in memory and SQLite system_config with TTL."""
    exp_val = time.time() + ttl_seconds
    _MEMORY_CACHE[cache_key] = (value, exp_val)

    db_key = f"cache.harvester.{cache_key}"
    db_exp_key = f"cache.harvester_exp.{cache_key}"
    try:
        async with AsyncSessionLocal() as session:
            for k, v in [(db_key, str(value)), (db_exp_key, str(exp_val))]:
                stmt = sqlite_insert(SystemConfig).values(key=k, value=v)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": stmt.excluded.value},
                )
                await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.warning("BrowserHarvester: failed to persist cache for %s: %s", cache_key, e)


async def _ensure_browser_binaries() -> bool:
    """Ensure playwright / camoufox and browser binaries are ready.
    Downloads them on-demand if missing.
    """
    global _BINARY_CHECKED
    if _BINARY_CHECKED:
        return True

    def _sync_setup() -> bool:
        # In the frozen desktop exe there is no pip / venv to install from.
        # A bare `import camoufox` only proves the Python package was
        # collected into the exe — NOT that a browser was fetched for this
        # user. Verify an actual installed browser instead; when missing, the
        # caller falls through to provision-on-consent fetching.
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            try:
                import camoufox  # noqa: F401  # type: ignore
            except ImportError:
                return False
            return _installed_browser_present() is not None
        # Check if camoufox or playwright is installed
        try:
            import camoufox  # type: ignore
            if is_frozen:
                return True
        except ImportError:
            if is_frozen:
                return False
            pass

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            # Check if chromium / firefox browser is present
            try:
                with sync_playwright() as p:
                    # Test launching headless
                    try:
                        browser = p.chromium.launch(headless=True)
                        browser.close()
                        return True
                    except Exception:
                        if is_frozen:
                            # Can't install from inside the exe; surface failure
                            # so the caller logs it instead of hanging on pip.
                            logger.warning(
                                "BrowserHarvester: no usable browser in frozen exe "
                                "(check PLAYWRIGHT_BROWSERS_PATH)"
                            )
                            return False
                        # Install chromium
                        logger.info("BrowserHarvester: Installing Playwright chromium binaries...")
                        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                        return True
            except Exception as e:
                logger.warning("BrowserHarvester: playwright browser test failed: %s", e)
        except ImportError:
            logger.info("BrowserHarvester: Installing playwright package...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                return True
            except Exception as exc:
                logger.error("BrowserHarvester: failed to install playwright: %s", exc)
                return False

        return False

    success = await asyncio.to_thread(_sync_setup)
    if success:
        _BINARY_CHECKED = True
        _set_browser_status("ready")
    else:
        # No usable browser: kick off provision-on-consent fetching in the
        # background (one-shot guarded) so a later harvest/warm-start finds
        # it. This attempt still reports unavailable.
        try:
            trigger_browser_fetch()
        except Exception:
            pass
    return success


def trigger_harvester_download() -> None:
    """Spawn background task to install browser dependencies upon consent."""
    global _DOWNLOAD_TASK
    if _BINARY_CHECKED:
        return
    if _DOWNLOAD_TASK is None or _DOWNLOAD_TASK.done():
        try:
            loop = asyncio.get_running_loop()
            _DOWNLOAD_TASK = loop.create_task(_ensure_browser_binaries())
        except RuntimeError:
            pass


# ── Warm browser internals (sync thread owns the browser) ────────────────────

def _warm_launch() -> tuple[Any, Any, Any, Any] | None:
    """Launch a persistent browser + page. Returns (closer, browser, page, kind).

    closer is a zero-arg callable that shuts everything down.
    kind is "camoufox" or "playwright".
    """
    # 1. Try Camoufox (anti-bot stealth) first
    try:
        from camoufox.sync_api import Camoufox  # type: ignore

        cf = Camoufox(headless=True)
        browser = cf.__enter__()
        page = browser.new_page()

        def _close_cf() -> None:
            try:
                page.close()
            except Exception:
                pass
            try:
                cf.__exit__(None, None, None)
            except Exception:
                pass

        return (_close_cf, browser, page, "camoufox")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("WarmBrowser: Camoufox launch failed: %s", e)
        # Missing browser (or crashed one): trigger provision-on-consent
        # fetching so the warm browser starts once the fetch lands.
        try:
            trigger_browser_fetch()
        except Exception:
            pass

    # 2. Fallback to Playwright chromium
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        pw = sync_playwright()
        p = pw.start()
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        def _close_pw() -> None:
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

        return (_close_pw, browser, page, "playwright")
    except Exception as e:
        logger.error("WarmBrowser: Playwright launch failed: %s", e)
        return None


def _warm_worker() -> None:
    """Daemon thread body: owns one persistent browser + page, serves jobs."""
    global _BINARY_CHECKED
    q = _WARM_QUEUE
    if q is None:
        return

    launched = _warm_launch()
    if launched is None:
        logger.error("WarmBrowser: could not launch any browser, warm mode disabled")
        return
    closer, _browser, page, kind = launched
    logger.info("WarmBrowser: persistent %s browser launched", kind)

    # Pre-navigate so the first real harvest skips even the first goto.
    try:
        page.goto(_WARM_PREWARM_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_timeout(3000)
        except Exception:
            pass
    except Exception as e:
        logger.debug("WarmBrowser: prewarm navigation failed (non-fatal): %s", e)
    _WARM_READY.set()

    def _restart() -> bool:
        nonlocal closer, page, kind
        try:
            closer()
        except Exception:
            pass
        relaunched = _warm_launch()
        if relaunched is None:
            return False
        closer, _b2, page, kind = relaunched
        try:
            page.goto(_WARM_PREWARM_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        logger.info("WarmBrowser: restarted persistent %s browser after crash", kind)
        return True

    while not _WARM_STOP.is_set():
        try:
            job = q.get(timeout=1.0)
        except queue.Empty:
            # Heartbeat: detect a dead page early, restart if needed.
            try:
                page.evaluate("1+1")
            except Exception:
                logger.warning("WarmBrowser: heartbeat failed, restarting browser")
                _WARM_READY.clear()
                if not _restart():
                    logger.error("WarmBrowser: restart failed, giving up")
                    return
                _WARM_READY.set()
            continue

        if job is None:  # sentinel for shutdown
            break
        try:
            kind_job, url, key, wait_selector, fut = job
            if fut.done():
                continue
            try:
                if kind_job == "ls":
                    # Navigate only when URL changed; otherwise reuse live DOM.
                    try:
                        cur = page.url or ""
                    except Exception:
                        cur = ""
                    if not cur.startswith(url):
                        page.goto(url, wait_until="networkidle", timeout=30000)
                        try:
                            page.wait_for_timeout(3000)
                        except Exception:
                            pass
                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=5000)
                        except Exception:
                            pass
                    val = page.evaluate(f"localStorage.getItem({repr(key)})")
                    if not val:
                        # SPA may need a reload to repopulate storage; one retry.
                        try:
                            page.reload(wait_until="networkidle", timeout=30000)
                            try:
                                page.wait_for_timeout(3000)
                            except Exception:
                                pass
                            val = page.evaluate(f"localStorage.getItem({repr(key)})")
                        except Exception:
                            pass
                    if not fut.done():
                        fut.set_result(val)
                else:  # html
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if key:  # key carries the selector for html jobs
                        try:
                            page.wait_for_selector(key, timeout=10000)
                            element = page.query_selector(key)
                            html = element.inner_html() if element else page.content()
                        except Exception:
                            html = page.content()
                    else:
                        html = page.content()
                    if not fut.done():
                        fut.set_result(html)
            except Exception as e:
                logger.warning("WarmBrowser: job failed (%s), restarting browser: %s", kind_job, e)
                _WARM_READY.clear()
                if _restart():
                    _WARM_READY.set()
                if not fut.done():
                    fut.set_exception(e)
        finally:
            try:
                q.task_done()
            except Exception:
                pass

    try:
        closer()
    except Exception:
        pass
    _WARM_READY.clear()
    logger.info("WarmBrowser: stopped")


def ensure_warm_browser(prewarm_url: str | None = None) -> bool:
    """Start the persistent browser thread (non-blocking). Returns True if running/starting."""
    global _WARM_QUEUE, _WARM_THREAD
    with _WARM_THREAD_LOCK:
        if prewarm_url:
            global _WARM_PREWARM_URL
            _WARM_PREWARM_URL = prewarm_url
        if _WARM_THREAD is not None and _WARM_THREAD.is_alive():
            return True
        _WARM_STOP.clear()
        _WARM_QUEUE = queue.Queue()
        _WARM_THREAD = threading.Thread(
            target=_warm_worker, daemon=True, name="warm-browser"
        )
        _WARM_THREAD.start()
        return True


def shutdown_warm_browser(timeout: float = 10.0) -> None:
    """Stop the persistent browser thread and close the browser."""
    global _WARM_QUEUE, _WARM_THREAD
    _WARM_STOP.set()
    try:
        if _WARM_QUEUE is not None:
            _WARM_QUEUE.put_nowait(None)
    except Exception:
        pass
    t = _WARM_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning("WarmBrowser: thread did not exit within %.1fs", timeout)
    _WARM_READY.clear()
    _WARM_QUEUE = None
    _WARM_THREAD = None


async def _warm_submit(kind: str, url: str, key: str | None, wait_selector: str | None) -> Any | None:
    """Submit one job to the warm browser and await it without blocking the loop.

    Returns the page result, or None if the warm browser is unavailable.
    Raises on job failure so callers can fall back to the cold path.
    """
    if not _WARM_READY.is_set() or _WARM_QUEUE is None:
        return None
    loop = asyncio.get_running_loop()
    fut: concurrent.futures.Future = concurrent.futures.Future()
    try:
        _WARM_QUEUE.put_nowait((kind, url, key or wait_selector, wait_selector, fut))
    except Exception:
        return None

    def _wait() -> Any:
        return fut.result(timeout=_WARM_JOB_TIMEOUT)

    return await asyncio.to_thread(_wait)


async def harvest_local_storage(url: str, key: str, wait_selector: str | None = None, ttl_seconds: int = 86400, force: bool = False) -> str | None:
    """Boot headless browser, navigate to URL, wait for network idle/selector, and extract localStorage key.

    Guarded by:
    1. User consent check (aborts if not consented)
    2. Cache check (returns cached value if valid; skipped when force=True,
       e.g. re-login after a 401 where the cached token is known stale)
    3. asyncio.Lock to avoid concurrent browser instances
    """
    if not await get_consent_status():
        logger.info("BrowserHarvester: harvest_local_storage skipped - advanced consent not granted.")
        return None

    cache_key = _get_cache_key("ls", url, key)
    if not force:
        cached = await get_cached_item(cache_key)
        if cached is not None:
            logger.debug("BrowserHarvester: returned cached local_storage for %s [%s]", url, key)
            return str(cached)

    # Fast path: persistent warm browser (no 8-12s launch).
    if _WARM_READY.is_set():
        try:
            warm_val = await _warm_submit("ls", url, key, wait_selector)
            if warm_val is not None:
                await set_cached_item(cache_key, warm_val, ttl_seconds=ttl_seconds)
                return str(warm_val)
            logger.debug("BrowserHarvester: warm browser returned empty for %s [%s], falling back to cold", url, key)
        except Exception as e:
            logger.debug("BrowserHarvester: warm path failed, falling back to cold: %s", e)

    async with _BROWSER_LOCK:
        # Double-check cache inside lock (skipped on force, same as above)
        if not force:
            cached = await get_cached_item(cache_key)
            if cached is not None:
                return str(cached)

        ready = await _ensure_browser_binaries()
        if not ready:
            logger.error("BrowserHarvester: browser binaries not available")
            return None

        def _sync_harvest() -> str | None:
            # 1. Try Camoufox if available (anti-bot stealth)
            try:
                from camoufox.sync_api import Camoufox  # type: ignore
                with Camoufox(headless=True) as browser:
                    page = browser.new_page()
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(3000)
                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=5000)
                        except Exception:
                            pass
                    val = page.evaluate(f"localStorage.getItem({repr(key)})")
                    if val is not None:
                        return val
            except ImportError:
                pass
            except Exception as e:
                logger.warning("BrowserHarvester Camoufox error: %s", e)
                try:
                    trigger_browser_fetch()
                except Exception:
                    pass

            # 2. Fallback to Playwright
            try:
                from playwright.sync_api import sync_playwright  # type: ignore
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                    )
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(3000)
                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=5000)
                        except Exception:
                            pass
                    val = page.evaluate(f"localStorage.getItem({repr(key)})")
                    browser.close()
                    return val
            except Exception as e:
                logger.error("BrowserHarvester Playwright error: %s", e)
                return None

        result = await asyncio.to_thread(_sync_harvest)
        if result is not None:
            await set_cached_item(cache_key, result, ttl_seconds=ttl_seconds)
        return result


async def harvest_public_html(url: str, selector: str | None = None, ttl_seconds: int = 86400) -> str | None:
    """Navigate to URL as anonymous visitor and return HTML of selector (or whole page).
    
    Guarded by:
    1. User consent check
    2. Cache check
    3. asyncio.Lock
    """
    if not await get_consent_status():
        logger.info("BrowserHarvester: harvest_public_html skipped - advanced consent not granted.")
        return None

    cache_key = _get_cache_key("html", url, selector or "all")
    cached = await get_cached_item(cache_key)
    if cached is not None:
        logger.debug("BrowserHarvester: returned cached html for %s", url)
        return str(cached)

    # Fast path: persistent warm browser.
    if _WARM_READY.is_set():
        try:
            warm_html = await _warm_submit("html", url, selector, None)
            if warm_html is not None:
                await set_cached_item(cache_key, warm_html, ttl_seconds=ttl_seconds)
                return str(warm_html)
            logger.debug("BrowserHarvester: warm browser returned empty html for %s, falling back to cold", url)
        except Exception as e:
            logger.debug("BrowserHarvester: warm html path failed, falling back to cold: %s", e)

    async with _BROWSER_LOCK:
        cached = await get_cached_item(cache_key)
        if cached is not None:
            return str(cached)

        ready = await _ensure_browser_binaries()
        if not ready:
            logger.error("BrowserHarvester: browser binaries not available")
            return None

        def _sync_harvest() -> str | None:
            # 1. Try Camoufox
            try:
                from camoufox.sync_api import Camoufox  # type: ignore
                with Camoufox(headless=True) as browser:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if selector:
                        page.wait_for_selector(selector, timeout=10000)
                        element = page.query_selector(selector)
                        return element.inner_html() if element else page.content()
                    return page.content()
            except ImportError:
                pass
            except Exception as e:
                logger.warning("BrowserHarvester Camoufox html error: %s", e)
                try:
                    trigger_browser_fetch()
                except Exception:
                    pass

            # 2. Fallback to Playwright
            try:
                from playwright.sync_api import sync_playwright  # type: ignore
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                    )
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if selector:
                        try:
                            page.wait_for_selector(selector, timeout=10000)
                            element = page.query_selector(selector)
                            if element:
                                html = element.inner_html()
                                browser.close()
                                return html
                        except Exception:
                            pass
                    html = page.content()
                    browser.close()
                    return html
            except Exception as e:
                logger.error("BrowserHarvester Playwright html error: %s", e)
                return None

        result = await asyncio.to_thread(_sync_harvest)
        if result is not None:
            await set_cached_item(cache_key, result, ttl_seconds=ttl_seconds)
        return result
