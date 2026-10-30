import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { adminTour } from '@/lib/widgetTours/definitions/admin';
import { adminDoc } from '@/lib/widgetDocs/definitions/admin';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'admin-header',
  'admin-create',
  'admin-users',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('ADMIN Widget Tour and Documentation', () => {
  const adminSourcePath = path.resolve(__dirname, '../../components/widgets/AdminWidget.tsx');
  const adminSource = readFileSync(adminSourcePath, 'utf-8');

  it('has 3 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(adminTour.steps).toHaveLength(3);

    const ids = adminTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(3);

    for (const step of adminTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = adminTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in AdminWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(adminSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to adminDoc metadata and screenshot structure', () => {
    expect(adminDoc.command).toBe('ADMIN');
    expect(adminDoc.kind).toBe('panel');
    expect(adminDoc.screenshot?.src).toBe('/docs/widgets/ADMIN.png');
    expect(adminDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = adminDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = adminDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
