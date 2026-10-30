import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { WIDGET_TOURS, WIDGET_TOUR_COMMANDS } from '@/lib/widgetTours';

/**
 * Every tour action is a click on a `data-widget-tour-click` element inside the
 * widget. A selector that matches nothing would stall a step for two seconds and
 * then skip it, so the source is checked directly here for all widgets at once.
 */
const WIDGET_SOURCES: Record<string, string[]> = {
  TOP: ['MoversWidget.tsx'],
  WATCH: ['WatchWidget.tsx'],
  CHART: ['ChartWidget.tsx'],
  ORDER: ['OrderWidget.tsx'],
  POS: ['PosWidget.tsx'],
  COMPANY: ['CompanyWidget.tsx', 'CompanyTabs/FundamentalsTab.tsx', 'CompanyTabs/DealsTab.tsx'],
  LARGEDEALS: ['LargedealsWidget.tsx'],
  BREAKOUTS: ['BreakoutsWidget.tsx'],
  NEWS: ['NewsWidget.tsx'],
  ANALYSIS: ['AnalysisWidget.tsx'],
  NOTIF: ['NotifWidget.tsx'],
  SCAN: ['NotifWidget.tsx'],
  ANNC: ['AnnouncementsWidget.tsx'],
  SCREENER: ['ScreenerWidget.tsx'],
  AI: ['AiWidget.tsx', 'AiToolbar.tsx', 'AiInputBar.tsx'],
  PORTFOLIO: ['PortfolioWidget.tsx'],
  PICKS: ['AiPicksWidget.tsx'],
  ADMIN: ['AdminWidget.tsx'],
  DOCS: ['DocsWidget.tsx'],
};

const WIDGETS_DIR = path.resolve(__dirname, '../../components/widgets');

function readSources(command: string): string {
  const files = WIDGET_SOURCES[command] ?? [];
  return files
    .map((file) => readFileSync(path.join(WIDGETS_DIR, file), 'utf-8'))
    .join('\n');
}

/** Turns `[data-widget-tour-click="tab-bulk"]` or `tab-bulk` into `tab-bulk`. */
function selectorValue(selector: string): string {
  const match = /data-widget-tour-click="([^"]+)"/.exec(selector);
  return match ? match[1] : selector;
}

/**
 * Accepts a literal attribute, or a template literal sharing the same prefix,
 * such as `data-widget-tour-click={`tab-${tab.id}`}`.
 */
function hasClickTarget(source: string, value: string): boolean {
  if (source.includes(`data-widget-tour-click="${value}"`)) {
    return true;
  }
  const prefix = value.split('-')[0];
  return source.includes(`data-widget-tour-click={\`${prefix}-\${`);
}

describe('widget tour actions resolve to real click targets', () => {
  for (const command of WIDGET_TOUR_COMMANDS) {
    const tour = WIDGET_TOURS[command];
    it(`${tour.command} actions and restore actions exist in the widget source`, () => {
      const source = readSources(tour.command);
      expect(source.length).toBeGreaterThan(0);

      const selectors = [
        ...(tour.startActions ?? []),
        ...tour.steps.flatMap((step) => step.actions ?? []),
        ...(tour.restoreActions ?? []),
      ].map((action) => action.selector);

      for (const selector of selectors) {
        const value = selectorValue(selector);
        expect(hasClickTarget(source, value), `${tour.command}: ${selector}`).toBe(true);
      }
    });
  }

  it('declares a source file for every tour command', () => {
    for (const command of WIDGET_TOUR_COMMANDS) {
      expect(WIDGET_SOURCES[command], command).toBeDefined();
    }
  });
});
