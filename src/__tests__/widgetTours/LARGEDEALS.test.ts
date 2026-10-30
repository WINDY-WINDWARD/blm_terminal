import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { largedealsTour } from '@/lib/widgetTours/definitions/largedeals';
import { largedealsDoc } from '@/lib/widgetDocs/definitions/largedeals';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'largedeals-tabs',
  'largedeals-filters',
  'largedeals-kpis',
  'largedeals-table',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('LARGEDEALS Widget Tour and Documentation', () => {
  const widgetSourcePath = path.resolve(__dirname, '../../components/widgets/LargedealsWidget.tsx');
  const widgetSource = readFileSync(widgetSourcePath, 'utf-8');

  it('has 4 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(largedealsTour.steps).toHaveLength(4);

    const ids = largedealsTour.steps.map((step) => step.id);
    expect(new Set(ids).size).toBe(4);

    for (const step of largedealsTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    expect(largedealsTour.steps.map((step) => step.anchor)).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in LargedealsWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(widgetSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to largedealsDoc metadata and screenshot structure', () => {
    expect(largedealsDoc.command).toBe('LARGEDEALS');
    expect(largedealsDoc.kind).toBe('panel');
    expect(largedealsDoc.screenshot?.src).toBe('/docs/widgets/LARGEDEALS.png');
    expect(largedealsDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    expect(largedealsDoc.sections.map((section) => section.heading)).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = largedealsDoc.sections.find(
      (section) => section.heading === 'Fields and how to read them',
    );
    expect(fieldsSection).toBeDefined();

    const fields = fieldsSection?.items as DocField[];
    expect(fields.length).toBeGreaterThan(0);

    for (const field of fields) {
      expect(field.name.trim().length).toBeGreaterThan(0);
      expect(field.desc.trim().length).toBeGreaterThan(0);
    }
  });
});
