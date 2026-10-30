export type WidgetTourPlacement = 'auto' | 'below' | 'above';

export interface WidgetTourStep {
  id: string;
  anchor: string;
  title: string;
  body: string;
  placement?: WidgetTourPlacement;
}

export interface WidgetTourDefinition {
  command: string;
  title: string;
  steps: WidgetTourStep[];
}

export type WidgetTourMode = 'auto' | 'replay';

export interface WidgetTourRequest {
  panelId: string;
  command: string;
  mode: WidgetTourMode;
}
