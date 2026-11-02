import type { WidgetTourDefinition } from '../types';

export const docsTour: WidgetTourDefinition = {
  command: 'DOCS',
  title: 'Documentation',
  restoreActions: [{ selector: '[data-widget-tour-click="back-to-index"]' }],
  steps: [
    {
      id: 'open-reference-index',
      anchor: 'docs-index',
      title: 'Widget reference index',
      body: 'Every widget has one row: command, one-line summary, a SEEN or NOT RUN badge, and a TOUR button. The tour opens the CHART page next.',
      placement: 'below',
    },
    {
      id: 'read-widget-doc',
      anchor: 'docs-doc-view',
      title: 'One page per widget',
      body: 'Each page lists what the widget shows, its controls, the meaning of every field, and how fresh the data is. Focus any other panel and this view follows it automatically.',
      placement: 'below',
      actions: [{ selector: '[data-widget-tour-click="doc-chart"]' }],
    },
    {
      id: 'inspect-screenshot',
      anchor: 'docs-screenshot',
      title: 'Live widget screenshot',
      body: 'The screenshot is captured from the running terminal, so it matches the build you use. Click the image to open it full size inside this panel. Press Escape to close the zoom.',
      placement: 'below',
    },
    {
      id: 'replay-a-tour',
      anchor: 'docs-replay-tour',
      title: 'Replay any widget tour',
      body: 'Keep the target widget open in another panel, then click REPLAY TOUR. The tour runs inside that widget. If the widget is not open, the panel shows a hint with the command to open.',
      placement: 'below',
    },
  ],
};
