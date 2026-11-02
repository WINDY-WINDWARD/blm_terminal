export interface DocField {
  name: string;
  desc: string;
}

export interface DocSection {
  heading: string;
  body?: string;
  items?: DocField[] | string[];
}

export interface WidgetDocScreenshot {
  src: string;
  alt: string;
  caption: string;
}

export interface WidgetDoc {
  command: string;
  title: string;
  summary: string;
  kind: 'panel' | 'modal';
  order: number;
  screenshot?: WidgetDocScreenshot;
  sections: DocSection[];
}
