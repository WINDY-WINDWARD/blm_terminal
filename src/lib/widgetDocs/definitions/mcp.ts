import type { DocField, WidgetDoc } from '../types';

export const mcpDoc: WidgetDoc = {
  command: 'mcp',
  title: 'MCP SERVER',
  summary:
    'Local Model Context Protocol server exposing market data, fundamentals, filings, and terminal tools to external AI clients.',
  kind: 'panel',
  order: 210,
  sections: [
    {
      heading: 'Connection',
      body: 'The server endpoint is /api/mcp/mcp. The development server listens at http://127.0.0.1:4455/api/mcp/mcp. The desktop application listens at http://127.0.0.1:4747/api/mcp/mcp when enabled.',
    },
    {
      heading: 'Enabling on desktop',
      items: [
        'Open Settings > Intelligence in the terminal.',
        'Toggle the Local MCP Server setting to enabled.',
        'Set the port field between 1024 and 65535, or keep 4747.',
        'Restart the desktop application to apply the port changes.',
      ],
    },
    {
      heading: 'Transport facts',
      items: [
        {
          name: 'Protocol',
          desc: 'Streamable HTTP transport that operates in stateless mode with JSON responses.',
        },
        {
          name: 'Authentication',
          desc: 'No authentication header is required. The service binds to localhost only.',
        },
        {
          name: 'Headers',
          desc: "Clients should send Accept 'application/json, text/event-stream'. Most clients send this header automatically.",
        },
      ] as DocField[],
    },
    {
      heading: 'Client setup',
      body: 'Replace 4747 with your configured port if you use a custom port number.',
      items: [
        {
          name: 'Claude Code',
          desc: 'claude mcp add --transport http blm http://127.0.0.1:4747/api/mcp/mcp',
        },
        {
          name: 'Codex (~/.codex/config.toml)',
          desc: '[mcp_servers.blm]\nurl = "http://127.0.0.1:4747/api/mcp/mcp"',
        },
        {
          name: 'Antigravity (mcp_config.json)',
          desc: '{"mcpServers":{"blm":{"serverUrl":"http://127.0.0.1:4747/api/mcp/mcp"}}}',
        },
      ] as DocField[],
    },
    {
      heading: 'Tools',
      body: 'The server provides 69 tools. Send a tools/list request to enumerate all registered tools.',
      items: [
        {
          name: 'Health & Status',
          desc: 'Health checks and service status queries.',
        },
        {
          name: 'Watchlists & Positions',
          desc: 'CRUD operations for watchlists and trading positions.',
        },
        {
          name: 'Market Data & Screeners',
          desc: 'NSE quotes, gainers, losers, Screener metrics, and TQL scans.',
        },
        {
          name: 'Filings & News',
          desc: 'Corporate announcements, regulatory filings, and company news.',
        },
        {
          name: 'Documents & Analytics',
          desc: 'PDF parsing, CSV analysis, company FDM summaries, and portfolio optimization.',
        },
      ] as DocField[],
    },
  ],
};
