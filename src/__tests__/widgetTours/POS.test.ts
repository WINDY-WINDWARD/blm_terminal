import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { posTour } from '@/lib/widgetTours/definitions/pos';
import { posDoc } from '@/lib/widgetDocs/definitions/pos';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'pos-mode-toggle',
  'pos-paper-tabs',
  'pos-kpi-deck',
  'pos-matrix-table',
  'pos-add-leg-action',
  'pos-square-off-action',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('POS Widget Tour and Documentation', () => {
  const posSourcePath = path.resolve(__dirname, '../../components/widgets/PosWidget.tsx');
  const posSource = readFileSync(posSourcePath, 'utf-8');

  it('has 6 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(posTour.steps).toHaveLength(6);

    const ids = posTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(6);

    for (const step of posTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = posTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in PosWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(posSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to posDoc metadata, kind, and screenshot structure', () => {
    expect(posDoc.command).toBe('POS');
    expect(posDoc.kind).toBe('panel');
    expect(posDoc.screenshot?.src).toBe('/docs/widgets/POS.png');
    expect(posDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = posDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = posDoc.sections.find((s) => s.heading === 'Fields and how to read them');
    expect(fieldsSection).toBeDefined();
    expect(Array.isArray(fieldsSection?.items)).toBe(true);

    const fields = fieldsSection?.items as DocField[];
    expect(fields.length).toBeGreaterThan(0);

    for (const field of fields) {
      expect(field.name.trim().length).toBeGreaterThan(0);
      expect(field.desc.trim().length).toBeGreaterThan(0);
    }
  });

  it('does not mention Day P&L anywhere in posDoc', () => {
    const serializedDoc = JSON.stringify(posDoc);
    expect(serializedDoc).not.toContain('Day P&L');
  });
});
