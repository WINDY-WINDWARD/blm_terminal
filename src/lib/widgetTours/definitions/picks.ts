import type { WidgetTourDefinition } from '../types';

export const picksTour: WidgetTourDefinition = {
  command: 'PICKS',
  title: 'AI Picks',
  steps: [
    {
      id: 'picks-tabs',
      anchor: 'picks-tabs',
      title: 'Lifecycle Tabs',
      body: 'PICKS holds new recommendations. ACTIVE holds positions you acted on. HISTORY holds closed trades. ABANDONED holds rejected setups. The tour opens ACTIVE next.',
      actions: [{ selector: '[data-widget-tour-click="tab-active"]' }],
    },
    {
      id: 'picks-triggers',
      anchor: 'picks-triggers',
      title: 'Scan and Evaluation Triggers',
      body: 'Admins run the morning Hunter scan and the evening Verifier pass. A live banner shows progress. Both buttons call the model, so the tour never presses them.',
      actions: [{ selector: '[data-widget-tour-click="tab-picks"]' }],
    },
    {
      id: 'picks-card',
      anchor: 'picks-card',
      title: 'Trade Pick Card',
      body: 'Direction, entry, target, and stop define the setup. Open P&L updates from live ticks and is not a realised result.',
      optional: true,
    },
    {
      id: 'picks-details',
      anchor: 'picks-details',
      title: 'Open the Thesis',
      body: 'DETAILS opens the full model thesis and the status controls. The tour spotlights the control and does not open the modal. Replay the tour from DOCS with both panels open.',
      optional: true,
    },
  ],
};
