import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { scanTour } from '@/lib/widgetTours/definitions/scan';
import { scanDoc } from '@/lib/widgetDocs/definitions/scan';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'scan-scope',
  'scan-heatmap-toggle',
  'scan-filters',
  'scan-popout-actions',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('SCAN Widget Tour and Documentation', () => {
  const notifSourcePath = path.resolve(__dirname, '../../components/widgets/NotifWidget.tsx');
  const notifSource = readFileSync(notifSourcePath, 'utf-8');

  it('has 4 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(scanTour.steps).toHaveLength(4);

    const ids = scanTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(4);

    for (const step of scanTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = scanTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in NotifWidget.tsx as a data-widget-tour attribute', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(notifSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to scanDoc metadata and screenshot structure', () => {
    expect(scanDoc.command).toBe('SCAN');
    expect(scanDoc.kind).toBe('panel');
    expect(scanDoc.screenshot?.src).toBe('/docs/widgets/SCAN.png');
    expect(scanDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = scanDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = scanDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
