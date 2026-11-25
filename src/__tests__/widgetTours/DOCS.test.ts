import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { docsTour } from '@/lib/widgetTours/definitions/docs';
import { docsDoc } from '@/lib/widgetDocs/definitions/docs';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'docs-index',
  'docs-doc-view',
  'docs-screenshot',
  'docs-replay-tour',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('DOCS Widget Tour and Documentation', () => {
  const sourcePath = path.resolve(__dirname, '../../components/widgets/DocsWidget.tsx');
  const source = readFileSync(sourcePath, 'utf-8');

  it('has 4 tour steps with unique kebab-case ids and non-empty copy', () => {
    expect(docsTour.steps).toHaveLength(4);

    const ids = docsTour.steps.map((step) => step.id);
    expect(new Set(ids).size).toBe(4);

    for (const step of docsTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    expect(docsTour.steps.map((step) => step.anchor)).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in DocsWidget.tsx as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(source).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to docsDoc metadata and screenshot structure', () => {
    expect(docsDoc.command).toBe('DOCS');
    expect(docsDoc.kind).toBe('panel');
    expect(docsDoc.screenshot?.src).toBe('/docs/widgets/DOCS.png');
    expect(docsDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    expect(docsDoc.sections.map((section) => section.heading)).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = docsDoc.sections.find(
      (s) => s.heading === 'Fields and how to read them',
    );
    const fields = fieldsSection?.items as DocField[];

    expect(fields.length).toBeGreaterThan(0);
    for (const field of fields) {
      expect(field.name.trim().length).toBeGreaterThan(0);
      expect(field.desc.trim().length).toBeGreaterThan(0);
    }
  });
});
