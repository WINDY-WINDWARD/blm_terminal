# MCP Server Integration Guide

The BLM Analytics backend provides an embedded Model Context Protocol (MCP) server. External AI agents can connect over Streamable HTTP to query market data, fundamentals, filings, watchlists, positions, and analytics.

---

## 1. Overview & Connection Architecture

The server uses the Streamable HTTP transport in stateless mode with direct JSON responses. It mounts under the `/api/mcp` prefix. The full endpoint URL is `/api/mcp/mcp`.

- **Development endpoint**: `http://127.0.0.1:4455/api/mcp/mcp`
- **Desktop endpoint**: `http://127.0.0.1:4747/api/mcp/mcp` (once enabled)
- **Binding**: Loopback only (`127.0.0.1`).
- **Authentication**: No authentication token is required. The launch-token guard exempts `/api/mcp`.

---

## 2. Server Setup

### Development Mode

To run the backend directly from source:

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Activate your virtual environment:
   ```bash
   source .venv/bin/activate
   # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Start the FastAPI server:
   ```bash
   uvicorn main:app --port 4455
   ```

### Desktop Application

In the desktop application, the MCP server is optional and disabled by default.

To enable the server:

1. Open **Settings > Intelligence** in the desktop application.
2. Toggle **Local MCP Server** to enabled.
3. Configure your desired port (default: `4747`, allowed range: `1024-65535`).
4. Restart the desktop application to apply the change.

---

## 3. Protocol & JSON-RPC Requests

The server accepts standard JSON-RPC 2.0 requests over HTTP POST.

### Required Headers

Clients must send the following headers:
- `Content-Type: application/json`
- `Accept: application/json, text/event-stream`

### Example Request (`tools/list`)

```bash
curl -X POST http://127.0.0.1:4455/api/mcp/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

### Python Example

```python
import requests

url = "http://127.0.0.1:4455/api/mcp/mcp"
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
}

response = requests.post(url, json=payload, headers=headers, timeout=30)
data = response.json()
print(f"Discovered {len(data['result']['tools'])} tools")
```

---

## 4. Client Configurations

If you changed the port from `4747`, replace `4747` with your configured port.

### Claude Code

Run this command in your terminal:

```bash
claude mcp add --transport http blm http://127.0.0.1:4747/api/mcp/mcp
```

### Codex

Add this configuration to `~/.codex/config.toml`:

```toml
[mcp_servers.blm]
url = "http://127.0.0.1:4747/api/mcp/mcp"
```

### Antigravity

Add this configuration to `mcp_config.json`:

```json
{
  "mcpServers": {
    "blm": {
      "serverUrl": "http://127.0.0.1:4747/api/mcp/mcp"
    }
  }
}
```

---

## 5. Tools & Capabilities

The server registers 69 tools. Call `tools/list` to inspect the full tool schemas.

The tools cover five functional categories:
1. **Health & Status**: Verify backend connectivity and system health.
2. **Watchlists & Positions**: Manage watchlists and track user positions.
3. **Market Data & Screeners**: Query NSE quotes, movers, Screener fundamentals, and run TQL queries.
4. **Filings & News**: Read corporate filings, announcements, and sentiment-tagged news.
5. **Documents & Analytics**: Parse PDFs, analyze CSV data, view company FDM profiles, and optimize portfolios.

---

## 6. Implementation Details & Lifespan Architecture

The backend uses the official MCP Python SDK (`mcp>=2,<3`). It instantiates the `MCPServer` class in `app/mcp_server.py`.

FastAPI does not run sub-app lifespans when an application mounts via `app.mount("/api/mcp", ...)`. To ensure the MCP session manager starts correctly, `main.py` enters the session manager explicitly within its main lifespan context:

```python
async with mcp_server.mcp._lowlevel_server._session_manager.run():
    yield
```

This workaround uses a private SDK API (`_lowlevel_server._session_manager`).

### Testing

The test suite in `backend/tests/test_mcp.py` covers this private API integration and verifies tool discovery.

Before running the test suite, start the server on port 4455:

```bash
uvicorn main:app --port 4455
```

Then run pytest from the backend directory:

```bash
pytest tests/test_mcp.py
```

To run only non-NSE tests:

```bash
pytest -m "not slow" tests/test_mcp.py
```

---

## 7. History

The backend previously used a stdio transport (`run_mcp_stdio.py`) and a Claude Desktop extension bundle (`blm-mcp-bundle`). Both were removed intentionally in commit `10b22408` during desktop app conversion. Modern clients support direct Streamable HTTP connections, and the HTTP mount was restored to provide native loopback connectivity.
