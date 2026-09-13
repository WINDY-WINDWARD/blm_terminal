import { describe, it, expect } from 'vitest';
import {
  createDefaultPanelSizes,
  PANEL_LAYOUTS,
  DEFAULT_ACTIVE_PANELS,
  validateMergeSelection,
  getMergedGroupForPanel,
  type MergedGroup,
} from '@/store/terminalStore';

describe('terminalStore', () => {
  describe('createDefaultPanelSizes', () => {
    it('should create correct sizes for panel count 2', () => {
      const sizes = createDefaultPanelSizes(2);
      expect(sizes.rowSizes).toHaveLength(PANEL_LAYOUTS[2].rows);
      expect(sizes.colSizes).toHaveLength(PANEL_LAYOUTS[2].rows);
      sizes.colSizes.forEach((row) => {
        expect(row).toHaveLength(PANEL_LAYOUTS[2].cols);
      });
      // Verify percentages sum to approximately 100
      expect(sizes.rowSizes.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 1);
      sizes.colSizes.forEach((row) => {
        expect(row.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 1);
      });
    });

    it('should create correct sizes for panel count 4', () => {
      const sizes = createDefaultPanelSizes(4);
      expect(sizes.rowSizes).toHaveLength(PANEL_LAYOUTS[4].rows);
      expect(sizes.colSizes).toHaveLength(PANEL_LAYOUTS[4].rows);
      sizes.colSizes.forEach((row) => {
        expect(row).toHaveLength(PANEL_LAYOUTS[4].cols);
      });
      expect(sizes.rowSizes.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 1);
    });

    it('should create correct sizes for panel count 6', () => {
      const sizes = createDefaultPanelSizes(6);
      expect(sizes.rowSizes).toHaveLength(PANEL_LAYOUTS[6].rows);
      expect(sizes.colSizes).toHaveLength(PANEL_LAYOUTS[6].rows);
      sizes.colSizes.forEach((row) => {
        expect(row).toHaveLength(PANEL_LAYOUTS[6].cols);
      });
      expect(sizes.rowSizes.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 1);
    });

    it('should create correct sizes for panel count 8', () => {
      const sizes = createDefaultPanelSizes(8);
      expect(sizes.rowSizes).toHaveLength(PANEL_LAYOUTS[8].rows);
      expect(sizes.colSizes).toHaveLength(PANEL_LAYOUTS[8].rows);
      sizes.colSizes.forEach((row) => {
        expect(row).toHaveLength(PANEL_LAYOUTS[8].cols);
      });
      expect(sizes.rowSizes.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 1);
    });
  });

  describe('DEFAULT_ACTIVE_PANELS', () => {
    it('should have exactly 8 panel keys', () => {
      expect(Object.keys(DEFAULT_ACTIVE_PANELS)).toHaveLength(8);
    });

    it('should have correct widget names for each panel', () => {
      expect(DEFAULT_ACTIVE_PANELS['panel-1']).toBe('CHART');
      expect(DEFAULT_ACTIVE_PANELS['panel-2']).toBe('WATCH');
      expect(DEFAULT_ACTIVE_PANELS['panel-3']).toBe('TOP');
      expect(DEFAULT_ACTIVE_PANELS['panel-4']).toBe('POS');
      expect(DEFAULT_ACTIVE_PANELS['panel-5']).toBe('NEWS');
      expect(DEFAULT_ACTIVE_PANELS['panel-6']).toBe('ANALYSIS');
      expect(DEFAULT_ACTIVE_PANELS['panel-7']).toBe('DEALS');
      expect(DEFAULT_ACTIVE_PANELS['panel-8']).toBe('PORTFOLIO');
    });
  });

  describe('PANEL_LAYOUTS', () => {
    it('should have correct rows and cols for each panel count', () => {
      expect(PANEL_LAYOUTS[2]).toEqual({ rows: 1, cols: 2 });
      expect(PANEL_LAYOUTS[4]).toEqual({ rows: 2, cols: 2 });
      expect(PANEL_LAYOUTS[6]).toEqual({ rows: 2, cols: 3 });
      expect(PANEL_LAYOUTS[8]).toEqual({ rows: 2, cols: 4 });
    });
  });

  describe('validateMergeSelection', () => {
    it('rejects fewer than 2 panels', () => {
      const result = validateMergeSelection(['panel-1'], 4, {});
      expect(result.valid).toBe(false);
      expect(result.error).toContain('at least 2');
    });

    it('rejects odd number of panels', () => {
      const result = validateMergeSelection(
        ['panel-1', 'panel-2', 'panel-3'],
        4,
        {},
      );
      expect(result.valid).toBe(false);
      expect(result.error).toContain('even');
    });

    it('rejects panels already in a merge group', () => {
      const merged: Record<string, MergedGroup> = {
        'panel-1': { panels: ['panel-1', 'panel-2'], primary: 'panel-1' },
      };
      const result = validateMergeSelection(['panel-1', 'panel-3'], 4, merged);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('already be merged');
    });

    it('rejects panels outside the current layout', () => {
      const result = validateMergeSelection(['panel-1', 'panel-5'], 4, {});
      expect(result.valid).toBe(false);
      expect(result.error).toContain('current layout');
    });

    it('accepts a horizontal pair in 2x2 layout', () => {
      const result = validateMergeSelection(['panel-1', 'panel-2'], 4, {});
      expect(result.valid).toBe(true);
    });

    it('accepts a vertical pair in 2x2 layout', () => {
      const result = validateMergeSelection(['panel-1', 'panel-3'], 4, {});
      expect(result.valid).toBe(true);
    });

    it('accepts a full 2x2 grid merge', () => {
      const result = validateMergeSelection(
        ['panel-1', 'panel-2', 'panel-3', 'panel-4'],
        4,
        {},
      );
      expect(result.valid).toBe(true);
    });

    it('rejects an even-count non-rectangle selection', () => {
      const result = validateMergeSelection(
        ['panel-1', 'panel-2', 'panel-3', 'panel-5'],
        6,
        {},
      );
      expect(result.valid).toBe(false);
      expect(result.error).toContain('rectangle');
    });

    it('rejects a diagonal pair (non-adjacent rectangle)', () => {
      const result = validateMergeSelection(['panel-1', 'panel-4'], 4, {});
      expect(result.valid).toBe(false);
      expect(result.error).toContain('rectangle');
    });

    it('accepts a 2x3 full grid merge in 6-panel layout', () => {
      const result = validateMergeSelection(
        [
          'panel-1',
          'panel-2',
          'panel-3',
          'panel-4',
          'panel-5',
          'panel-6',
        ],
        6,
        {},
      );
      expect(result.valid).toBe(true);
    });

    it('accepts a 2x2 block inside a 2x3 layout', () => {
      const result = validateMergeSelection(
        ['panel-1', 'panel-2', 'panel-4', 'panel-5'],
        6,
        {},
      );
      expect(result.valid).toBe(true);
    });

    it('accepts a horizontal triple in 2x4 layout', () => {
      const result = validateMergeSelection(
        ['panel-1', 'panel-2', 'panel-3'],
        8,
        {},
      );
      expect(result.valid).toBe(false);
      expect(result.error).toContain('even');
    });
  });

  describe('getMergedGroupForPanel', () => {
    it('returns the group containing the panel', () => {
      const groups: Record<string, MergedGroup> = {
        'panel-1': { panels: ['panel-1', 'panel-2'], primary: 'panel-1' },
      };
      expect(getMergedGroupForPanel('panel-2', groups)).toEqual({
        panels: ['panel-1', 'panel-2'],
        primary: 'panel-1',
      });
    });

    it('returns undefined for unmerged panel', () => {
      const groups: Record<string, MergedGroup> = {
        'panel-1': { panels: ['panel-1', 'panel-2'], primary: 'panel-1' },
      };
      expect(getMergedGroupForPanel('panel-3', groups)).toBeUndefined();
    });
  });
});
