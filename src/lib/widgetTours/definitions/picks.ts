import type { WidgetTourDefinition } from '../types';

export const picksTour: WidgetTourDefinition = {
  command: 'PICKS',
  title: 'AI Picks',
  steps: [
    {
      id: 'picks-tabs',
      anchor: 'picks-tabs',
      title: 'Category Tabs',
      body: 'Switch between PICKS, ACTIVE, HISTORY, and ABANDONED tabs to filter trade recommendations by lifecycle state.',
    },
    {
      id: 'picks-triggers',
      anchor: 'picks-triggers',
      title: 'Scan and Evaluation Triggers',
      body: 'Trigger morning Hunter scans or evening Verifier loops. A live progress banner displays the execution status and percentage.',
    },
    {
      id: 'picks-card',
      anchor: 'picks-card',
      title: 'Trade Pick Card',
      body: 'Review symbol, direction, entry, target, and stop levels. Live ticks update the open profit and loss continuously.',
    },
    {
      id: 'picks-modal',
      anchor: 'picks-modal',
      title: 'Pick Details and Thesis Modal',
      body: 'Open the modal to review the full AI thesis and manage trade status. You can replay this tour from DOCS with both panels open.',
    },
  ],
};
