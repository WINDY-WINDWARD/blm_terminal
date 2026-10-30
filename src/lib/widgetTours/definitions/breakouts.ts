import type { WidgetTourDefinition } from '../types';

export const breakoutsTour: WidgetTourDefinition = {
  command: 'BREAKOUTS',
  title: '52-Week Breakouts',
  steps: [
    {
      id: 'breakouts-view-tabs',
      anchor: 'breakouts-tabs',
      title: 'Radar View Tabs',
      body: 'Switch between the ALL MATRIX overview and dedicated tables for 52W High, 52W Low, Volume Shockers, and Repeated breakouts.',
    },
    {
      id: 'breakouts-matrix-grid',
      anchor: 'breakouts-matrix',
      title: 'Four-Card Matrix Grid',
      body: 'Scan 52-Week High Breakout Radar, 52-Week Low Breakdown Radar, Volume Shockers, and Repeated Persistence cards simultaneously.',
    },
    {
      id: 'breakouts-volume-shockers',
      anchor: 'breakouts-volume',
      title: 'Volume Shockers Radar',
      body: 'Spot institutional footprints with surge multipliers against 1-week average volume. Breakouts backed by volume expansion confirm stronger momentum.',
    },
    {
      id: 'breakouts-table-rows',
      anchor: 'breakouts-rows',
      title: 'Breakout Table Rows',
      body: 'Inspect clearance statuses like UPPER CIRCUIT, FRESH ATH, or MULTI-YR HIGH. Click any symbol to sync across panels. Replay this tour from DOCS with both panels open.',
    },
  ],
};
