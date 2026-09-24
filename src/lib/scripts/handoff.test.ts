import { describe, expect, it } from 'vitest';
import { buildRefinePrompt, findAiPanel, resolveChartPanel } from './handoff';

describe('resolveChartPanel', () => {
  it('prefers the focused CHART panel', () => {
    expect(
      resolveChartPanel({ 'panel-1': 'CHART', 'panel-2': 'CHART' }, 'panel-2'),
    ).toBe('panel-2');
  });

  it('falls back to the first CHART panel when focus is elsewhere', () => {
    expect(
      resolveChartPanel({ 'panel-1': 'WATCH', 'panel-2': 'CHART' }, 'panel-1'),
    ).toBe('panel-2');
  });

  it('falls back to focused panel, then panel-1, when no CHART exists', () => {
    expect(resolveChartPanel({ 'panel-1': 'WATCH' }, 'panel-1')).toBe('panel-1');
    expect(resolveChartPanel({}, null)).toBe('panel-1');
  });
});

describe('findAiPanel', () => {
  it('returns the AI panel id or null', () => {
    expect(findAiPanel({ 'panel-1': 'CHART', 'panel-3': 'AI' })).toBe('panel-3');
    expect(findAiPanel({ 'panel-1': 'CHART' })).toBeNull();
  });
});

describe('buildRefinePrompt', () => {
  it('includes name, id and rev when present', () => {
    expect(buildRefinePrompt('RSI bands', 7, 3)).toBe(
      'Refine chart script "RSI bands" (id 7, rev 3): ',
    );
  });

  it('omits rev when unknown', () => {
    expect(buildRefinePrompt('RSI bands', 7, null)).toBe(
      'Refine chart script "RSI bands" (id 7): ',
    );
  });
});
