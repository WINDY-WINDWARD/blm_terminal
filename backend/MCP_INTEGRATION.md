# Integrating BLM Analytics MCP with Desktop Clients

The BLM Analytics backend exposes a powerful Model Context Protocol (MCP) server that provides AI agents with direct access to NSE market data, corporate filings, screener data, and the stock universe.

There are **two ways** to connect Claude Desktop to BLM Analytics:

1. **MCP Bundle (Recommended)**: A pre-built `.mcpb` plugin that requires no configuration — just build and install
2. **Direct Integration**: Configure Claude Desktop to run the Python stdio server directly

---

## Option 1: MCP Bundle (Recommended)

The easiest way to use BLM Analytics with Claude Desktop. Build once, install with one click.

### Build

```bash
# Install mcpb CLI (one-time)
npm install -g @anthropic-ai/mcpb

# Build the bundle
cd blm-mcp-bundle
node build.js                    # Uses localhost:4455
node build.js --port 8000       # Custom port
PYTHON_BACKEND_URL=http://host:4455 node build.js  # From env
```

This creates `blm-mcp-proxy.mcpb` in the `blm-mcp-bundle/` directory.

### Install

1. Open Claude Desktop
2. Go to **Developer → Extensions → Install Extension**
3. Select the `.mcpb` file
4. Enter the backend host/port in the settings UI
5. Enable the extension

**Benefits:**
- Zero configuration
- Works cross-platform (Windows, macOS)
- Auto-updates when reinstalled
- 28 tools available immediately

See [`blm-mcp-bundle/README.md`](../blm-mcp-bundle/README.md) for full documentation.

---

## Option 2: Direct Integration

While the FastAPI application hosts the MCP server over **HTTP (Stateless Mode)** at `http://127.0.0.1:8000/api/mcp/mcp`, most desktop AI applications (like Claude Desktop and Perplexity Desktop) require the **stdio (Standard I/O) transport**.

This guide explains how to connect your desktop AI assistants to the BLM Analytics MCP server using `stdio`.

## Prerequisites

1. **Python Environment**: Ensure the backend virtual environment is fully set up.
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
2. **Database**: Ensure your database is migrated (normally handled automatically when you run the backend).

---

## 1. The Stdio Entrypoint

We have provided a dedicated script to run the MCP server in `stdio` mode without needing to start the full FastAPI web server. This script is located at:

```
backend/run_mcp_stdio.py
```

It simply imports the `mcp` instance and runs it:
```python
from app.mcp_server import mcp

if __name__ == "__main__":
    mcp.run()
```

---

## 2. Claude Desktop Integration

Claude Desktop natively supports MCP servers via `stdio`. You need to add the BLM Analytics server to its configuration file.

### Locate the Configuration File
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

If the file does not exist, create it.

### Update the Configuration

Add the following JSON snippet to your configuration file. **Important:** Replace `/path/to/blm_terminal` with the actual absolute path to your cloned repository.

```json
{
  "mcpServers": {
    "blm-analytics": {
      "command": "/path/to/blm_terminal/backend/.venv/bin/python",
      "args": [
        "/path/to/blm_terminal/backend/run_mcp_stdio.py"
      ],
      "env": {
        "PYTHONPATH": "/path/to/blm_terminal/backend"
      }
    }
  }
}
```

### Restart Claude Desktop
Completely quit Claude Desktop (Cmd+Q / Ctrl+Q) and relaunch it. You should now see a new **hammer (tools)** icon in the Claude interface indicating that the `blm-analytics` tools are available. You can ask Claude: *"What are the top gainers on NSE today?"* and it will query your local server.

---

## 3. Perplexity Desktop Integration

*Note: Perplexity Desktop's support for local MCP servers is evolving. If it uses a standard `mcpServers` JSON configuration (similar to Claude or Cursor), the setup is identical.*

If Perplexity Desktop supports a UI-based MCP configuration:
1. Open **Settings** -> **Advanced** / **Developer** -> **MCP Servers**
2. Click **Add Server**
3. Configure the following fields:
   - **Name**: `BLM Analytics`
   - **Type / Transport**: `stdio`
   - **Command**: `/path/to/blm_terminal/backend/.venv/bin/python`
   - **Arguments**: `/path/to/blm_terminal/backend/run_mcp_stdio.py`
   - **Environment Variables**: Add `PYTHONPATH` with the value `/path/to/blm_terminal/backend`

### Alternative: Using the HTTP Stateless Endpoint

If Perplexity Desktop eventually supports connecting to **Stateless HTTP** MCP endpoints natively, you can point it directly to your running FastAPI server instead of using `stdio`:

- **Endpoint URL**: `http://127.0.0.1:8000/api/mcp/mcp`
- **Requirements**: Requires sending the `mcp-protocol-version: 2025-03-26` header. Ensure the FastAPI backend is currently running (`uvicorn main:app`).

---

## 4. LM Studio Integration

LM Studio (v0.3.17+) supports both `stdio` and remote HTTP MCP servers via an `mcp.json` file.

### Option A — Stateless HTTP (recommended, no subprocess)

This uses the running FastAPI backend directly. **Start the backend first:**

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open LM Studio → **Program** tab (right-hand sidebar) → **Install ▸ Edit mcp.json**, then add:

```json
{
  "mcpServers": {
    "blm-analytics": {
      "url": "http://127.0.0.1:8000/api/mcp/mcp"
    }
  }
}
```

Save the file. LM Studio will pick up the server immediately — no restart required. The FastAPI server already runs in `stateless_http=True` / `json_response=True` mode, so LM Studio's HTTP transport connects without any handshake.

### Option B — Stdio (no backend server required)

If you prefer not to keep the FastAPI process running, use the stdio entrypoint instead:

```json
{
  "mcpServers": {
    "blm-analytics": {
      "command": "/path/to/blm_terminal/backend/.venv/bin/python",
      "args": [
        "/path/to/blm_terminal/backend/run_mcp_stdio.py"
      ],
      "env": {
        "PYTHONPATH": "/path/to/blm_terminal/backend"
      }
    }
  }
}
```

Replace `/path/to/blm_terminal` with the absolute path to your cloned repository.

> **Tip:** LM Studio's `mcp.json` follows [Cursor's notation](https://docs.cursor.com/context/model-context-protocol). Copy only the content inside `"mcpServers": { … }` if LM Studio prompts you to paste a snippet.

---

## 5. Troubleshooting

- **Server Disconnected / Tool Execution Failed**: This usually means the Python executable path is incorrect or the virtual environment is missing dependencies. Verify the absolute paths in your `command` and `args`.
- **Database Locked / Access Errors**: Because the `stdio` process runs independently of the FastAPI process, it connects to the same SQLite database. SQLite allows concurrent reads, but if you do heavy concurrent writes, you might see locking. (The current MCP tools are primarily read-only, with slight caching/upserting for filings and screener sessions).
- **Logs**: To debug the `stdio` server, you can manually run the command in your terminal. It communicates over stdout, so any Python tracebacks will be printed directly to the console if it crashes on startup.
