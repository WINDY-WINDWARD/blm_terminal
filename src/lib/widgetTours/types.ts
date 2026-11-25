export type WidgetTourPlacement = 'auto' | 'below' | 'above' | 'left' | 'right';

export interface WidgetTourClick {
  /** CSS selector resolved inside the tour panel. */
  selector: string;
}

export interface WidgetTourStep {
  id: string;
  anchor: string;
  title: string;
  body: string;
  placement?: WidgetTourPlacement;
  /** Clicks to run before this step is measured, so the tour can open sub-views. */
  actions?: WidgetTourClick[];
  /** Skip this step when its anchor does not exist once the actions settle. */
  optional?: boolean;
}

export interface WidgetTourDefinition {
  command: string;
  title: string;
  /** Clicks to run once, before the first step. */
  startActions?: WidgetTourClick[];
  /** Clicks to run when the tour closes, to undo a view the tour opened. */
  restoreActions?: WidgetTourClick[];
  steps: WidgetTourStep[];
}

export type WidgetTourMode = 'auto' | 'replay';

export interface WidgetTourRequest {
  panelId: string;
  command: string;
  mode: WidgetTourMode;
}
