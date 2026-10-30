import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { anncTour } from '@/lib/widgetTours/definitions/annc';
import { anncDoc } from '@/lib/widgetDocs/definitions/annc';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'annc-tabs',
  'annc-results-split',
  'annc-tabs',
  'annc-search',
  'annc-filing-open',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('ANNC Widget Tour and Documentation', () => {
  const anncSourcePath = path.resolve(__dirname, '../../components/widgets/AnnouncementsWidget.tsx');
  const anncSource = readFileSync(anncSourcePath, 'utf-8');

  it('has 5 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(anncTour.steps).toHaveLength(5);

    const ids = anncTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(5);

    for (const step of anncTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = anncTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in AnnouncementsWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(anncSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to anncDoc metadata and screenshot structure', () => {
    expect(anncDoc.command).toBe('ANNC');
    expect(anncDoc.kind).toBe('panel');
    expect(anncDoc.order).toBe(130);
    expect(anncDoc.screenshot?.src).toBe('/docs/widgets/ANNC.png');
    expect(anncDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = anncDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Controls"', () => {
    const controlsSection = anncDoc.sections.find((s) => s.heading === 'Controls');
    expect(controlsSection).toBeDefined();
    expect(Array.isArray(controlsSection?.items)).toBe(true);

    const fields = controlsSection?.items as DocField[];
    expect(fields.length).toBeGreaterThan(0);

    for (const field of fields) {
      expect(field.name.trim().length).toBeGreaterThan(0);
      expect(field.desc.trim().length).toBeGreaterThan(0);
    }
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = anncDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
