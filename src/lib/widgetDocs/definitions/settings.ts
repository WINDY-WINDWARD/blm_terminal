import type { DocField, WidgetDoc } from '../types';

export const settingsDoc: WidgetDoc = {
  command: 'SETTINGS',
  title: 'Settings',
  summary:
    'Configure terminal preferences: data extraction and browser provisioning, visible columns, layout, AI providers, and connection parameters.',
  kind: 'modal',
  order: 200,
  sections: [
    {
      heading: 'What it shows',
      body: 'Application settings grouped into categories. Changes are persisted to the local database and take effect immediately.',
    },
    {
      heading: 'Configuration areas',
      items: [
        { name: 'Data Extraction & Privacy', desc: 'Advanced Extraction consent plus the headless-browser provisioning status (unknown / ready / missing / downloading / failed) with download progress and a Retry button (shown for failed/missing). Granting consent triggers a backend Camoufox fetch; the status poll runs every 5s while consented and stops once ready.' },
        { name: 'Watchlist Columns', desc: 'Toggle which columns appear in the WATCH widget (LTP, CHG, MSFV, returns, RESULTS, ALERTS).' },
        { name: 'Movers Columns', desc: 'Toggle which columns appear in the TOP widget.' },
        { name: 'Panel Layout', desc: 'Switch between 2, 4, 6, or 8 panel grid layouts.' },
        { name: 'AI Provider', desc: 'Engine, keys/OAuth, and model list for the AI widget (auto-saved to system-config ai.*).' },
        { name: 'OpenAlgo', desc: 'API URL and key for broker connectivity (ORDER, POS execution).' },
      ] as DocField[],
    },
    {
      heading: 'How to use',
      items: [
        'Type SETTINGS or click the ⚙️ button in the CommandBar to open the Settings modal.',
        'Press Escape or click [CLOSE] to dismiss the modal.',
        'Changes to columns apply instantly — no page reload required.',
        'Layout changes resize all panels; drag dividers to adjust individual panel sizes.',
      ],
    },
  ],
};
