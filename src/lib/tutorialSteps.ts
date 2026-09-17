import type { DriveStep } from 'driver.js';

export interface TutorialStepDef {
  id: string;
  /** Command a user can type to open this widget manually */
  command: string;
  selector: string;
  title: string;
  description: string;
  actionType?: 'focus' | 'widget' | 'select' | 'merge' | 'unmerge' | 'layout';
}

/** Full tour: terminal basics + interactive hands-on actions + widget deep-dives. */
export const TUTORIAL_STEP_DEFS: TutorialStepDef[] = [
  {
    id: 'command-bar',
    command: '',
    selector: '#terminal-command-input',
    title: 'Command bar',
    description:
      'This is your control center. Type widget commands (CHART, WATCH, NEWS, SETTINGS), ' +
      'switch symbols (/RELIANCE), or manage layouts. Type TOUR anytime to replay this guide.',
  },
  {
    id: 'action-focus',
    command: '',
    selector: '[data-tour-panel-id="panel-2"]',
    title: 'Try it: Click to focus',
    description:
      'Click this panel (or any other panel) to focus it. Its border turns blue to show it is active—commands ' +
      'you type in the bar load into the focused panel. (Click to try, or click Next / Skip).',
    actionType: 'focus',
  },
  {
    id: 'action-widget',
    command: 'NEWS',
    selector: '#terminal-command-input',
    title: 'Try it: Change widget',
    description:
      'Now load a different widget into your focused panel. Click here, type NEWS (or WATCH or CHART), ' +
      'and press Enter! The focused panel will change instantly. (Or click Next / Skip).',
    actionType: 'widget',
  },
  {
    id: 'action-select',
    command: '',
    selector: '[data-tour="terminal-grid"]',
    title: 'Try it: Select panels (Ctrl+Click)',
    description:
      'Hold Ctrl (Cmd on Mac) and click two adjacent panels (e.g. Panel 1 and Panel 2). ' +
      'Their borders will turn gold to show they are selected together! (Or click Next / Skip).',
    actionType: 'select',
  },
  {
    id: 'action-merge',
    command: '',
    selector: '[data-tour="terminal-grid"]',
    title: 'Try it: Merge panels (Press M)',
    description:
      'With the panels selected in gold, press the "M" key on your keyboard to merge them into one expanded view! (Or click Next / Skip).',
    actionType: 'merge',
  },
  {
    id: 'action-unmerge',
    command: '',
    selector: '[data-tour="terminal-grid"]',
    title: 'Try it: Unmerge panel (Press U)',
    description:
      'Focus the merged panel and press "U" on your keyboard to unmerge and split it back into separate panels! (Or click Next / Skip).',
    actionType: 'unmerge',
  },
  {
    id: 'action-layout',
    command: 'LAYOUT',
    selector: '#terminal-command-input',
    title: 'Try it: Change panel layout',
    description:
      'You can switch your workspace grid between 2, 4, 6, or 8 panels. Try typing LAYOUT 6 or LAYOUT 2 in the command bar, ' +
      'or change it anytime in Settings! (Or click Next / Skip).',
    actionType: 'layout',
  },
  {
    id: 'chart',
    command: 'CHART',
    selector: '[data-tour-panel="CHART"]',
    title: 'CHART: price action',
    description:
      'Candlestick chart for the active symbol with indicators, a LIVE overlay line, and EOD comparisons. ' +
      'Switch symbols from the command bar and every symbol-aware widget follows.',
  },
  {
    id: 'watch',
    command: 'WATCH',
    selector: '[data-tour-panel="WATCH"]',
    title: 'WATCH: your watchlist',
    description:
      'Track real-time LTP, % change, and multi-timeframe returns for your portfolio. ' +
      'The top ticker tape follows your watchlist by default.',
  },
  {
    id: 'news',
    command: 'NEWS',
    selector: '[data-tour-panel="NEWS"]',
    title: 'NEWS: market & company feed',
    description:
      'Live financial headlines from iinvest and MoneyControl with sentiment and threat filters. ' +
      'The company tab follows the active symbol.',
  },
  {
    id: 'ai',
    command: 'AI',
    selector: '[data-tour-panel="AI"]',
    title: 'AI: market assistant',
    description:
      'Chat about any NSE stock, analyze fundamentals, or summarize corporate filings. ' +
      'Supports OpenCode Zen (with free & paid models) and Google Gemini.',
  },
  {
    id: 'scan',
    command: 'SCAN',
    selector: '[data-tour-panel="SCAN"]',
    title: 'SCAN & NOTIF: alerts',
    description:
      'The global scanner continuously monitors momentum, breakout, volume, and 52-week triggers across the market. ' +
      'Tune thresholds in Settings.',
  },
  {
    id: 'settings',
    command: 'SETTINGS',
    selector: '[data-tour-panel="SETTINGS"]',
    title: 'SETTINGS: connections',
    description:
      'Configure OpenAlgo trading connections, AI provider keys, ticker sources, window layouts, and scanner thresholds.',
  },
];

export interface BuiltTutorial {
  steps: (DriveStep & { actionType?: string })[];
  /** Defs skipped because their widget is not on screen */
  skipped: TutorialStepDef[];
}

/** Partition defs into present/missing and append a closing summary step.
 *  `exists` defaults to a DOM query; inject a stub in tests. */
export function buildTutorialSteps(
  exists: (selector: string) => boolean = (sel) =>
    typeof document !== 'undefined' && document.querySelector(sel) !== null,
  onActionStepHighlight?: (actionType: string | null) => void,
): BuiltTutorial {
  const present: TutorialStepDef[] = [];
  const skipped: TutorialStepDef[] = [];
  for (const def of TUTORIAL_STEP_DEFS) {
    (exists(def.selector) ? present : skipped).push(def);
  }

  const steps: (DriveStep & { actionType?: string })[] = present.map((def) => ({
    element: def.selector,
    actionType: def.actionType,
    popover: { title: def.title, description: def.description },
    onHighlightStarted: () => {
      onActionStepHighlight?.(def.actionType ?? null);
    },
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
    onHighlightStarted: () => {
      onActionStepHighlight?.(null);
    },
  });

  return { steps, skipped };
}
