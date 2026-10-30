import { describe, expect, it } from 'vitest';
import { WIDGET_TOUR_COMMANDS, WIDGET_TOURS } from '@/lib/widgetTours';
import { DOCS_INDEX, WIDGET_DOCS } from '@/lib/widgetDocs';

const EXPECTED_PANEL_COMMANDS = [
  'TOP',
  'WATCH',
  'CHART',
  'ORDER',
  'POS',
  'COMPANY',
  'LARGEDEALS',
  'BREAKOUTS',
  'NEWS',
  'ANALYSIS',
  'NOTIF',
  'SCAN',
  'ANNC',
  'SCREENER',
  'AI',
  'PORTFOLIO',
  'PICKS',
  'ADMIN',
  'DOCS',
];

describe('Widget Tours Registry', () => {
  it('has exactly 19 tour definitions and each command appears once', () => {
    expect(WIDGET_TOUR_COMMANDS).toHaveLength(19);

    const commandSet = new Set(WIDGET_TOUR_COMMANDS);
    expect(commandSet.size).toBe(19);

    for (const cmd of EXPECTED_PANEL_COMMANDS) {
      expect(commandSet.has(cmd)).toBe(true);
      const def = WIDGET_TOURS[cmd];
      expect(def).toBeDefined();
      expect(def.command).toBe(cmd);
      expect(def.title).toBeTruthy();
      expect(Array.isArray(def.steps)).toBe(true);
    }
  });

  it('includes all 19 panel commands plus SETTINGS in WIDGET_DOCS, and SCRIPTS is absent', () => {
    expect(WIDGET_DOCS['SCRIPTS']).toBeUndefined();
    expect(DOCS_INDEX.some((d) => d.command === 'SCRIPTS')).toBe(false);

    for (const cmd of EXPECTED_PANEL_COMMANDS) {
      expect(WIDGET_DOCS[cmd]).toBeDefined();
      expect(WIDGET_DOCS[cmd].kind).toBe('panel');
    }

    expect(WIDGET_DOCS['SETTINGS']).toBeDefined();
    expect(WIDGET_DOCS['SETTINGS'].kind).toBe('modal');
  });

  it('every screenshot-bearing panel doc points at /docs/widgets/<COMMAND>.png', () => {
    // ORDER is the only exception: it has no usable capture without a broker gateway.
    for (const cmd of EXPECTED_PANEL_COMMANDS) {
      const doc = WIDGET_DOCS[cmd];
      expect(doc).toBeDefined();
      if (cmd === 'ORDER') {
        expect(doc.screenshot).toBeUndefined();
        continue;
      }
      expect(doc.screenshot).toBeDefined();
      expect(doc.screenshot?.src).toBe(`/docs/widgets/${cmd}.png`);
      expect(doc.screenshot?.alt).toBeTruthy();
      expect(doc.screenshot?.caption).toBeTruthy();
    }
  });
});
