import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { picksTour } from '@/lib/widgetTours/definitions/picks';
import { picksDoc } from '@/lib/widgetDocs/definitions/picks';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'picks-tabs',
  'picks-triggers',
  'picks-card',
  'picks-modal',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('PICKS Widget Tour and Documentation', () => {
  const picksSourcePath = path.resolve(__dirname, '../../components/widgets/AiPicksWidget.tsx');
  const picksSource = readFileSync(picksSourcePath, 'utf-8');

  it('has 4 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(picksTour.steps).toHaveLength(4);

    const ids = picksTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(4);

    for (const step of picksTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = picksTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in AiPicksWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(picksSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to picksDoc metadata and screenshot structure', () => {
    expect(picksDoc.command).toBe('PICKS');
    expect(picksDoc.kind).toBe('panel');
    expect(picksDoc.screenshot?.src).toBe('/docs/widgets/PICKS.png');
    expect(picksDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = picksDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = picksDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
