import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { orderTour } from '@/lib/widgetTours/definitions/order';
import { orderDoc } from '@/lib/widgetDocs/definitions/order';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'order-instrument-setup',
  'order-type-lot-selector',
  'order-product-selector',
  'order-risk-kpi-deck',
  'order-execution-buttons',
  'order-book-table',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('ORDER Widget Tour and Documentation', () => {
  const orderSourcePath = path.resolve(__dirname, '../../components/widgets/OrderWidget.tsx');
  const orderSource = readFileSync(orderSourcePath, 'utf-8');

  it('has 6 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(orderTour.steps).toHaveLength(6);

    const ids = orderTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(6);

    for (const step of orderTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = orderTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in OrderWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(orderSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to orderDoc metadata and omits the screenshot by design', () => {
    expect(orderDoc.command).toBe('ORDER');
    expect(orderDoc.kind).toBe('panel');
    expect(orderDoc.screenshot).toBeUndefined();
    expect(orderDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = orderDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = orderDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
