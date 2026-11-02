import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { companyTour } from '@/lib/widgetTours/definitions/company';
import { companyDoc } from '@/lib/widgetDocs/definitions/company';
import type { DocField } from '@/lib/widgetDocs/types';

const EXPECTED_ANCHORS = [
  'company-tabs',
  'company-ratios',
  'company-valuation',
  'company-deals',
  'company-corporate',
];

const EXPECTED_HEADINGS = [
  'What this widget shows',
  'Controls',
  'Fields and how to read them',
  'Data freshness and limits',
  'Guided tour',
];

const KEBAB_CASE_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

describe('COMPANY Widget Tour and Documentation', () => {
  const companySourcePath = path.resolve(__dirname, '../../components/widgets/CompanyWidget.tsx');
  const companySource = readFileSync(companySourcePath, 'utf-8');
  const fundamentalsSourcePath = path.resolve(
    __dirname,
    '../../components/widgets/CompanyTabs/FundamentalsTab.tsx',
  );
  const fundamentalsSource = readFileSync(fundamentalsSourcePath, 'utf-8');

  it('has 5 tour steps with unique kebab-case ids, non-empty titles, and non-empty bodies', () => {
    expect(companyTour.steps).toHaveLength(5);

    const ids = companyTour.steps.map((step) => step.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(5);

    for (const step of companyTour.steps) {
      expect(step.id).toMatch(KEBAB_CASE_REGEX);
      expect(step.title.trim().length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(40);
      expect(step.body.trim().length).toBeGreaterThan(0);
    }
  });

  it('matches the exact expected anchor list in order', () => {
    const anchors = companyTour.steps.map((step) => step.anchor);
    expect(anchors).toEqual(EXPECTED_ANCHORS);
  });

  it('contains every anchor as a data-widget-tour attribute in the owning source file', () => {
    expect(companySource).toContain('data-widget-tour="company-tabs"');
    expect(companySource).toContain('data-widget-tour="company-corporate"');
    expect(fundamentalsSource).toContain('data-widget-tour="company-ratios"');
    expect(fundamentalsSource).toContain('tourAnchor="company-valuation"');

    const dealsSource = readFileSync(
      path.resolve(__dirname, '../../components/widgets/CompanyTabs/DealsTab.tsx'),
      'utf-8',
    );
    expect(dealsSource).toContain('data-widget-tour="company-deals"');
  });

  it('wires every tour action to a data-widget-tour-click control', () => {
    expect(companySource).toContain('data-widget-tour-click={`tab-${tab.id}`}');

    const dealsSource = readFileSync(
      path.resolve(__dirname, '../../components/widgets/CompanyTabs/DealsTab.tsx'),
      'utf-8',
    );
    expect(dealsSource).toContain('data-widget-tour-click={`deals-${t.id}`}');

    for (const step of companyTour.steps) {
      for (const action of step.actions ?? []) {
        expect(action.selector).toMatch(/^(tab|deals)-[a-z0-9-]+$/);
      }
    }
  });

  it('conforms to companyDoc metadata and screenshot structure', () => {
    expect(companyDoc.command).toBe('COMPANY');
    expect(companyDoc.kind).toBe('panel');
    expect(companyDoc.screenshot?.src).toBe('/docs/widgets/COMPANY.png');
    expect(companyDoc.summary.length).toBeGreaterThan(20);
  });

  it('has the five expected documentation section headings in exact order', () => {
    const sectionHeadings = companyDoc.sections.map((section) => section.heading);
    expect(sectionHeadings).toEqual(EXPECTED_HEADINGS);
  });

  it('has non-empty name and desc for every DocField in "Controls"', () => {
    const controlsSection = companyDoc.sections.find((s) => s.heading === 'Controls');
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
    const fieldsSection = companyDoc.sections.find((s) => s.heading === 'Fields and how to read them');
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
