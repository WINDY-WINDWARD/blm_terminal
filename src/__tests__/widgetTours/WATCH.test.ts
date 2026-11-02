import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { watchTour } from '@/lib/widgetTours/definitions/watch';
import { watchDoc } from '@/lib/widgetDocs/definitions/watch';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'watch-selector-deck',
  'watch-add-symbol-form',
  'watch-breadth-indicator',
  'watch-table-header',
  'watch-alerts-cell',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('WATCH Widget Tour and Documentation', () => {
  const sourcePath = path.resolve(__dirname, '../../components/widgets/WatchWidget.tsx');
  const source = readFileSync(sourcePath, 'utf-8');

  it('has 5 tour steps with unique kebab-case ids and non-empty copy', () => {
    expect(watchTour.steps).toHaveLength(5);

    const ids = watchTour.steps.map((step) => step.id);
    expect(new Set(ids).size).toBe(5);

    for (const step of watchTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    expect(watchTour.steps.map((step) => step.anchor)).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in WatchWidget.tsx', () => {
    expect(source).toContain('data-widget-tour="watch-selector-deck"');
    expect(source).toContain('data-widget-tour="watch-add-symbol-form"');
    expect(source).toContain('data-widget-tour="watch-breadth-indicator"');
    expect(source).toContain('data-widget-tour="watch-table-header"');
    // ALERTS is a configurable column, so the attribute is conditional.
    expect(source).toContain(
      "data-widget-tour={colConfig?.label === 'ALERTS' ? 'watch-alerts-cell' : undefined}",
    );
  });

  it('conforms to watchDoc metadata and screenshot structure', () => {
    expect(watchDoc.command).toBe('WATCH');
    expect(watchDoc.kind).toBe('panel');
    expect(watchDoc.screenshot?.src).toBe('/docs/widgets/WATCH.png');
    expect(watchDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    expect(watchDoc.sections.map((section) => section.heading)).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every field', () => {
    const fieldsSection = watchDoc.sections.find(
      (section) => section.heading === 'Fields and how to read them',
    );
    expect(fieldsSection).toBeDefined();
    expect(Array.isArray(fieldsSection?.items)).toBe(true);

    const fields = fieldsSection?.items as DocField[];
    expect(fields.length).toBeGreaterThan(0);

    for (const field of fields) {
      expect(field.name.trim().length).toBeGreaterThan(0);
      expect(field.desc.trim().length).toBeGreaterThan(0);
    }
  });

  it('documents the fair value labels that the widget renders', () => {
    const text = JSON.stringify(watchDoc);
    expect(text).toContain('Undervalued');
    expect(text).toContain('Premium');
  });
});
