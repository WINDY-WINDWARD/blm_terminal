import { describe, expect, it } from 'vitest';
import { resolveWidgetPanel } from '@/lib/widgetTours/resolvePanel';

describe('resolveWidgetPanel', () => {
  it('returns focused panel when it matches the command', () => {
    const activePanels: Record<string, string> = {
      'panel-1': 'CHART',
      'panel-2': 'WATCH',
      'panel-3': 'NEWS',
      'panel-4': 'CHART',
    };
    // Both panel-1 and panel-4 have CHART, but panel-4 is focused
    const result = resolveWidgetPanel('CHART', activePanels, 4, 'panel-4');
    expect(result).toBe('panel-4');
  });

  it('returns first matching panel when focused panel does not match', () => {
    const activePanels: Record<string, string> = {
      'panel-1': 'WATCH',
      'panel-2': 'NEWS',
      'panel-3': 'CHART',
      'panel-4': 'CHART',
    };
    // panel-1 is focused (WATCH), so first match for CHART should be panel-3
    const result = resolveWidgetPanel('CHART', activePanels, 4, 'panel-1');
    expect(result).toBe('panel-3');
  });

  it('returns null when no panel matches the command', () => {
    const activePanels: Record<string, string> = {
      'panel-1': 'WATCH',
      'panel-2': 'POS',
    };
    const result = resolveWidgetPanel('CHART', activePanels, 2, 'panel-1');
    expect(result).toBeNull();
  });

  it('handles DOCS self-replay correctly', () => {
    const activePanels: Record<string, string> = {
      'panel-1': 'CHART',
      'panel-2': 'DOCS',
    };
    // DOCS self-replay from panel-2 when focused
    const resultFocused = resolveWidgetPanel('DOCS', activePanels, 2, 'panel-2');
    expect(resultFocused).toBe('panel-2');

    // DOCS replay when another panel is focused
    const resultUnfocused = resolveWidgetPanel('DOCS', activePanels, 2, 'panel-1');
    expect(resultUnfocused).toBe('panel-2');
  });
});
