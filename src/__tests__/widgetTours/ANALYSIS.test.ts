import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { analysisTour } from '@/lib/widgetTours/definitions/analysis';
import { analysisDoc } from '@/lib/widgetDocs/definitions/analysis';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'analysis-tabs',
  'analysis-kpis',
  'analysis-rail',
  'analysis-stats',
  'analysis-actions',
  'analysis-heat-controls',
  'analysis-heat-legend',
  'analysis-heatmap',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const CLICK_SELECTOR_REGEX = /data-widget-tour-click="([a-z0-9-]+)"/;

describe('ANALYSIS Widget Tour and Documentation', () => {
  const analysisSourcePath = path.resolve(__dirname, '../../components/widgets/AnalysisWidget.tsx');
  const analysisSource = readFileSync(analysisSourcePath, 'utf-8');

  it('has 8 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(analysisTour.steps).toHaveLength(8);

    const ids = analysisTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(8);

    for (const step of analysisTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = analysisTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in AnalysisWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(analysisSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('only clicks tab controls that carry a matching data-widget-tour-click attribute', () => {
    const clicks = analysisTour.steps.flatMap((step) => step.actions ?? []);
    expect(clicks.length).toBeGreaterThan(0);

    for (const action of clicks) {
      const match = CLICK_SELECTOR_REGEX.exec(action.selector);
      expect(match).not.toBeNull();
      expect(analysisSource).toContain(`data-widget-tour-click="${match?.[1]}"`);
    }
  });

  it('switches to Sectors before the rail and to Heatmap before the heat controls', () => {
    const stepFor = (id: string) => analysisTour.steps.find((step) => step.id === id);
    expect(stepFor('analysis-rail')?.actions?.[0].selector).toContain('tab-sectors');
    expect(stepFor('analysis-heat-controls')?.actions?.[0].selector).toContain('tab-heatmap');
    expect(analysisTour.steps[0].actions?.[0].selector).toContain('tab-summary');
  });

  it('conforms to analysisDoc metadata and screenshot structure', () => {
    expect(analysisDoc.command).toBe('ANALYSIS');
    expect(analysisDoc.kind).toBe('panel');
    expect(analysisDoc.screenshot?.src).toBe('/docs/widgets/ANALYSIS.png');
    expect(analysisDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = analysisDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = analysisDoc.sections.find((s) => s.heading === 'Fields and how to read them');
    expect(fieldsSection).toBeDefined();
    expect(Array.isArray(fieldsSection?.items)).toBe(true);

    const fields = fieldsSection?.items as DocField[];
    expect(fields.length).toBeGreaterThan(0);

    for (const field of fields) {
      expect(field.name.trim().length).toBeGreaterThan(0);
      expect(field.desc.trim().length).toBeGreaterThan(0);
    }
  });
});
