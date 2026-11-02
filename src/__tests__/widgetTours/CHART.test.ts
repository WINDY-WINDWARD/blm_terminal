import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { chartTour } from '@/lib/widgetTours/definitions/chart';
import { chartDoc } from '@/lib/widgetDocs/definitions/chart';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'chart-symbol-search',
  'chart-timeframe-bar',
  'chart-indicators-menu',
  'chart-scripts-menu',
  'chart-recenter-control',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('CHART Widget Tour and Documentation', () => {
  const chartSourcePath = path.resolve(__dirname, '../../components/widgets/ChartWidget.tsx');
  const chartSource = readFileSync(chartSourcePath, 'utf-8');

  it('has 5 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(chartTour.steps).toHaveLength(5);

    const ids = chartTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(5);

    for (const step of chartTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
      expect(step.body.split(/\s+/).filter(Boolean).length).toBeLessThanOrEqual(45);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = chartTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in ChartWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(chartSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to chartDoc metadata and screenshot structure', () => {
    expect(chartDoc.command).toBe('CHART');
    expect(chartDoc.kind).toBe('panel');
    expect(chartDoc.screenshot?.src).toBe('/docs/widgets/CHART.png');
    expect(chartDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = chartDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = chartDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
