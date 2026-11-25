import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { scanTour } from '@/lib/widgetTours/definitions/scan';
import { scanDoc } from '@/lib/widgetDocs/definitions/scan';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'scan-scope',
  'scan-view-mode',
  'scan-heatmap',
  'scan-categories',
  'scan-alert-card',
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

  it('has 6 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(scanTour.steps).toHaveLength(6);

    const ids = scanTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(6);

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

  it('contains every anchor in NotifWidget.tsx, through the shared tourId expression', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(notifSource).toMatch(new RegExp(`['"]${anchor}['"]`));
    }
    expect(notifSource).toContain("tourId === 'scan' ? 'scan-view-mode' : 'notif-view-mode'");
  });

  it('only clicks elements that are marked as tour actions', () => {
    const selectors = scanTour.steps.flatMap((step) => step.actions ?? []);
    expect(selectors.length).toBeGreaterThan(0);

    for (const action of selectors) {
      const name = action.selector.match(/data-widget-tour-click="([^"]+)"/)?.[1];
      expect(name).toBeTruthy();
      expect(notifSource).toContain(`data-widget-tour-click="${name}"`);
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
