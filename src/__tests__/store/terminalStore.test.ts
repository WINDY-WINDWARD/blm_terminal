import { describe, it, expect } from 'vitest';
import {
  createDefaultPanelSizes,
  PANEL_LAYOUTS,
  DEFAULT_ACTIVE_PANELS,
  type PanelCount,
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
      expect(DEFAULT_ACTIVE_PANELS['panel-8']).toBe('ORDER');
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
});