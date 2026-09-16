import type { DriveStep } from 'driver.js';

export interface TutorialStepDef {
  id: string;
  /** Command a user can type to open this widget manually */
  command: string;
  selector: string;
  title: string;
  description: string;
}

/** Full tour: terminal basics + per-widget deep-dives, in walk order. */
export const TUTORIAL_STEP_DEFS: TutorialStepDef[] = [
  {
    id: 'command-bar',
    command: '',
    selector: '#terminal-command-input',
    title: 'Command bar',
    description:
      'Type a widget command (CHART, WATCH, NEWS…) to load it into the focused panel. ' +
      'Type / followed by a symbol (e.g. /RELIANCE) to switch the global symbol. ' +
      'Type TOUR anytime to replay this guide.',
  },
  {
    id: 'panels',
    command: '',
    selector: '[data-tour-panel="TOP"]',
    title: 'Panels: focus, select, merge',
    description:
      'Click a panel to focus it (blue border) — commands load there. ' +
      'Ctrl+click panels to select them (gold), then press M to merge into one big view. ' +
      'Focus a merged panel and press U to unmerge. Changing the panel count in Settings resets merges.',
  },
  {
    id: 'chart',
    command: 'CHART',
    selector: '[data-tour-panel="CHART"]',
    title: 'CHART: price action',
    description:
      'Candlestick chart for the active symbol with indicators and a LIVE overlay. ' +
      'Switch symbols from the command bar and every symbol-aware widget follows.',
  },
  {
    id: 'watch',
    command: 'WATCH',
    selector: '[data-tour-panel="WATCH"]',
    title: 'WATCH: your watchlist',
    description:
      'Add symbols here to track LTP, change, and multi-timeframe returns. ' +
      'The top ticker tape follows your watchlist by default.',
  },
  {
    id: 'news',
    command: 'NEWS',
    selector: '[data-tour-panel="NEWS"]',
    title: 'NEWS: market & company feed',
    description:
      'Live headlines with source, sentiment, and threat filters. ' +
      'The company tab follows the active symbol.',
  },
  {
    id: 'ai',
    command: 'AI',
    selector: '[data-tour-panel="AI"]',
    title: 'AI: market assistant',
    description:
      'Chat about the active symbol, summarize news and announcements. ' +
      'Needs an AI key — you set one during setup, or add it later in Settings.',
  },
  {
    id: 'scan',
    command: 'SCAN',
    selector: '[data-tour-panel="SCAN"]',
    title: 'SCAN & NOTIF: alerts',
    description:
      'The global scanner flags momentum, volume, and 52-week triggers across the market. ' +
      'Tune thresholds in Settings (admin).',
  },
  {
    id: 'settings',
    command: 'SETTINGS',
    selector: '[data-tour-panel="SETTINGS"]',
    title: 'SETTINGS: connections',
    description:
      'OpenAlgo trading connection, AI keys, ticker source, panel count, and scan thresholds ' +
      'all live here (admin-gated where sensitive).',
  },
];

export interface BuiltTutorial {
  steps: DriveStep[];
  /** Defs skipped because their widget is not on screen */
  skipped: TutorialStepDef[];
}

/** Partition defs into present/missing and append a closing summary step.
 *  `exists` defaults to a DOM query; inject a stub in tests. */
export function buildTutorialSteps(
  exists: (selector: string) => boolean = (sel) =>
    typeof document !== 'undefined' && document.querySelector(sel) !== null,
): BuiltTutorial {
  const present: TutorialStepDef[] = [];
  const skipped: TutorialStepDef[] = [];
  for (const def of TUTORIAL_STEP_DEFS) {
    (exists(def.selector) ? present : skipped).push(def);
  }

  const steps: DriveStep[] = present.map((def) => ({
    element: def.selector,
    popover: { title: def.title, description: def.description },
  }));

  const skippedHint =
    skipped.length > 0
      ? ` Not on screen right now: ${skipped
          .map((s) => `${s.title} (type ${s.command})`)
          .join(', ')}.`
      : '';
  steps.push({
    element: '#terminal-command-input',
    popover: {
      title: 'You are set up',
      description:
        `That's the tour. Type TOUR to replay it, or open DOCS for per-widget reference.${skippedHint}`,
    },
  });

  return { steps, skipped };
}
