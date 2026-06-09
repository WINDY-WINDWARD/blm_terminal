"""Sync-compatible NSE client (audit B.10 — drift-proof single source of truth).

This module used to hold a 545-LOC sync ``NSEClient`` class that
duplicated the HTTP / parsing logic in :mod:`app.services.nse_client_async`.
The two implementations had drifted apart in several places (e.g. parsing
of ``pChange`` / ``perChange``, EQ-series filtering, nsepython fallback).

After the audit refactor:

- :class:`NSEClientAsync` in :mod:`app.services.nse_client_async` is the
  single source of truth for NSE HTTP behaviour.
- :class:`NSEClient` in THIS module is a thin sync facade that delegates
  every method to ``NSEClientAsync`` via :func:`asyncio.run`.  It exists so
  the 8 sync call sites (routers, orchestrator, background tasks, MCP
  server) that historically imported this module keep working without a
  call-site change.
- :data:`nse_client` is the module-level singleton preserved for callers
  that import ``from app.services.nse_client import nse_client``.
- :class:`SymbolNotFoundError` is re-exported from the async module so
  existing ``except SymbolNotFoundError`` blocks keep working.

Behavioural note
----------------
A few methods had divergent implementations between the old sync class
and the async class.  The facade always uses the async implementation,
so callers that depended on the OLD sync behaviour will see the (more
correct) async behaviour.  This is the intentional outcome of the
"drift-proof" audit goal.  See ``app/services/nse_client_async.py`` for
the authoritative implementation.
"""

from __future__ import annotations

from app.services.nse_client_async import (  # noqa: F401 (re-export)
    NSEClient,
    NSEClientAsync,
    SymbolNotFoundError,
    nse_client,
    nse_client_async,
)


__all__ = [
    "NSEClient",
    "NSEClientAsync",
    "SymbolNotFoundError",
    "nse_client",
    "nse_client_async",
]
