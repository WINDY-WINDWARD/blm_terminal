import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { aiTour } from '@/lib/widgetTours/definitions/ai';
import { aiDoc } from '@/lib/widgetDocs/definitions/ai';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'ai-toolbar',
  'ai-mode-toggle',
  'ai-personas',
  'ai-input',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('AI Widget Tour and Documentation', () => {
  const aiSourcePath = path.resolve(__dirname, '../../components/widgets/AiWidget.tsx');
  const aiSource = [
    readFileSync(aiSourcePath, 'utf-8'),
    readFileSync(path.resolve(__dirname, '../../components/widgets/AiToolbar.tsx'), 'utf-8'),
    readFileSync(path.resolve(__dirname, '../../components/widgets/AiInputBar.tsx'), 'utf-8'),
  ].join('\n');

  it('has 4 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(aiTour.steps).toHaveLength(4);

    const ids = aiTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(4);

    for (const step of aiTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = aiTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor in the AI component files as data-widget-tour attributes', () => {
    for (const anchor of EXPECTED_ANCHORS) {
      expect(aiSource).toContain(`data-widget-tour="${anchor}"`);
    }
  });

  it('conforms to aiDoc metadata and screenshot structure', () => {
    expect(aiDoc.command).toBe('AI');
    expect(aiDoc.kind).toBe('panel');
    expect(aiDoc.screenshot?.src).toBe('/docs/widgets/AI.png');
    expect(aiDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = aiDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Fields and how to read them"', () => {
    const fieldsSection = aiDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
