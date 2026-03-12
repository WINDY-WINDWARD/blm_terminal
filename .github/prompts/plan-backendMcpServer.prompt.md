**Plan**

Mount a streamable HTTP MCP server into the existing FastAPI backend so it shares the current lifecycle, logging, DB access, and service singletons. The first iteration should expose the backend’s existing read-only GET API surface, excluding everything in the AI router.

**Steps**
1. Freeze scope from the current GET routes: include root health, market snapshots, corporate filings, screener read endpoints, and stock-universe reads; exclude all AI routes, including AI health.
2. Add the official Python MCP SDK in [backend/pyproject.toml](backend/pyproject.toml) and standardize on one runtime shape: FastMCP mounted into the existing FastAPI app.
3. Create a dedicated MCP module, likely [backend/app/mcp_server.py](backend/app/mcp_server.py) once implemented, with the MCP server instance, tool definitions, and shared error-mapping helpers. The tools should call service and DB logic directly rather than making internal HTTP calls back into FastAPI.
4. Mirror existing behavior from the current routers so MCP tools preserve symbol validation, screener auth gating, throttling/caching semantics, and upstream error handling. For corporate filings, return structured MCP data containing symbol, media type, and CSV text rather than a raw FastAPI response.
5. Mount the MCP app in [backend/main.py](backend/main.py) under a dedicated path such as `/api/mcp`, keeping the existing lifespan as the single startup/shutdown authority. That means migrations, cache cleanup, stock-universe scheduling, and `screener_client.init()` still run once.
6. Add targeted backend tests for MCP tool discovery, one happy-path tool per route family, and key failure cases such as invalid symbols, missing screener session, and NSE upstream errors.
7. Update [backend/README.md](backend/README.md) with the MCP endpoint, transport choice, startup instructions, and an explicit note that AI endpoints are not part of the MCP surface in v1.

**Relevant Files**
- [backend/main.py](backend/main.py): existing FastAPI app, lifespan, middleware, and router registration; this is the MCP mount point.
- [backend/pyproject.toml](backend/pyproject.toml): dependency changes for the MCP SDK.
- [backend/app/routers/nonpersistence.py](backend/app/routers/nonpersistence.py): source behavior for market GET endpoints, throttling, and cache rules.
- [backend/app/routers/corporatefilings.py](backend/app/routers/corporatefilings.py): existing CSV fetch/cache behavior to mirror in MCP.
- [backend/app/routers/screener.py](backend/app/routers/screener.py): validation, auth gating, caching, and screener read semantics.
- [backend/app/routers/stockuniverse.py](backend/app/routers/stockuniverse.py): DB-backed read patterns for stock-universe tools.
- [backend/app/services/nse_client.py](backend/app/services/nse_client.py): direct service layer for market and filing data.
- [backend/app/services/screener_client.py](backend/app/services/screener_client.py): direct service layer for screener search/company/trades.
- [backend/tests/test_endpoints.py](backend/tests/test_endpoints.py): current test style and likely reference for MCP coverage.
- [backend/README.md](backend/README.md): runtime and usage documentation.

**Verification**
1. Start the backend and confirm existing REST routes still behave unchanged.
2. Verify MCP tool discovery only shows the intended read-only tools plus any optional health diagnostic.
3. Run one tool from each included family and compare outputs against the equivalent REST endpoint.
4. Confirm corporate-filings MCP output preserves CSV content in structured form.
5. Confirm screener auth failures, invalid symbols, and upstream failures become clean MCP errors rather than uncaught exceptions.
6. Confirm startup/shutdown behavior still runs once and no duplicate background tasks are introduced.

**Decisions**
- Transport: mounted HTTP MCP inside the existing FastAPI app.
- Scope: all current GET APIs except everything under [backend/app/routers/ai_summarizer.py](backend/app/routers/ai_summarizer.py).
- Architecture: MCP tools should call shared service and DB logic directly, not re-enter the app over HTTP.
- Excluded for v1: AI routes, non-GET APIs, frontend work, and separate stdio support.

If you approve this plan, the next handoff can go straight into implementation.
