import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { screenerTour } from '@/lib/widgetTours/definitions/screener';
import { screenerDoc } from '@/lib/widgetDocs/definitions/screener';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'screener-intervals',
  'screener-query',
  'screener-actions',
  'screener-table',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('SCREENER Widget Tour and Documentation', () => {
  const screenerSourcePath = path.resolve(__dirname, '../../components/widgets/ScreenerWidget.tsx');
  const screenerSource = readFileSync(screenerSourcePath, 'utf-8');

  it('has 4 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(screenerTour.steps).toHaveLength(4);

    const ids = screenerTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(4);

    for (const step of screenerTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = screenerTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in ScreenerWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(screenerSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to screenerDoc metadata and screenshot structure', () => {
    expect(screenerDoc.command).toBe('SCREENER');
    expect(screenerDoc.kind).toBe('panel');
    expect(screenerDoc.screenshot?.src).toBe('/docs/widgets/SCREENER.png');
    expect(screenerDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = screenerDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = screenerDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
