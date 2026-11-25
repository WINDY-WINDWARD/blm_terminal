import { describe, expect, it } from 'vitest';
import { computePlacement, computeScrollDelta, intersectRects, spotlightRect } from '@/lib/widgetTours/placement';
import type { TourPlacement, TourRect } from '@/lib/widgetTours/placement';

function rect(top: number, left: number, width: number, height: number): TourRect {
  return { top, left, width, height };
}

function overlaps(a: TourRect, b: TourRect): boolean {
  return (
    a.left < b.left + b.width &&
    a.left + a.width > b.left &&
    a.top < b.top + b.height &&
    a.top + a.height > b.top
  );
}

function popoverRect(placement: TourPlacement): TourRect {
  return rect(placement.top, placement.left, placement.width, placement.maxHeight);
}

describe('computePlacement', () => {
  it('places the popover below a target near the top', () => {
    const target = rect(40, 40, 600, 120);
    const placement = computePlacement({
      target,
      panelWidth: 800,
      panelHeight: 600,
      popoverWidth: 300,
      popoverHeight: 220,
    });

    expect(placement.dock).toBe('none');
    expect(placement.top).toBeGreaterThan(target.top + target.height);
    expect(overlaps(popoverRect(placement), target)).toBe(false);
  });

  it('places the popover above a target near the bottom', () => {
    const target = rect(430, 60, 500, 120);
    const placement = computePlacement({
      target,
      panelWidth: 800,
      panelHeight: 600,
      popoverWidth: 300,
      popoverHeight: 220,
    });

    expect(placement.dock).toBe('none');
    expect(placement.top + placement.maxHeight).toBeLessThanOrEqual(target.top);
    expect(overlaps(popoverRect(placement), target)).toBe(false);
  });

  it('uses the side with room on a short, wide panel', () => {
    const target = rect(20, 20, 400, 260);
    const placement = computePlacement({
      target,
      panelWidth: 1000,
      panelHeight: 300,
      popoverWidth: 320,
      popoverHeight: 200,
    });

    expect(placement.dock).toBe('none');
    expect(placement.left).toBeGreaterThanOrEqual(target.left + target.width);
    expect(overlaps(popoverRect(placement), target)).toBe(false);
  });

  it('docks to a panel edge when no side fits', () => {
    const target = rect(20, 20, 760, 260);
    const placement = computePlacement({
      target,
      panelWidth: 800,
      panelHeight: 300,
      popoverWidth: 320,
      popoverHeight: 220,
    });

    expect(placement.dock).not.toBe('none');
    expect(placement.width).toBeGreaterThan(600);
    expect(placement.safe.height).toBeGreaterThan(0);
  });

  it('keeps every non-docked popover inside the panel', () => {
    const cases = [
      { target: rect(10, 10, 300, 80), height: 500 },
      { target: rect(200, 300, 300, 80), height: 500 },
      { target: rect(400, 10, 300, 80), height: 500 },
    ];

    for (const item of cases) {
      const placement = computePlacement({
        target: item.target,
        panelWidth: 700,
        panelHeight: item.height,
        popoverWidth: 300,
        popoverHeight: 200,
      });

      expect(placement.left).toBeGreaterThanOrEqual(0);
      expect(placement.left + placement.width).toBeLessThanOrEqual(700);
      expect(placement.top).toBeGreaterThanOrEqual(0);
      expect(placement.top + placement.maxHeight).toBeLessThanOrEqual(item.height);
    }
  });

  it('honours an explicit side when it has room', () => {
    const target = rect(200, 200, 200, 100);
    const placement = computePlacement({
      target,
      panelWidth: 900,
      panelHeight: 600,
      popoverWidth: 280,
      popoverHeight: 200,
      preference: 'right',
    });

    expect(placement.dock).toBe('none');
    expect(placement.left).toBeGreaterThanOrEqual(target.left + target.width);
  });
});

describe('computeScrollDelta', () => {
  it('scrolls forward when the target sits below the safe band', () => {
    const delta = computeScrollDelta(rect(400, 20, 300, 80), rect(8, 8, 760, 200));
    expect(delta.dy).toBe(272);
    expect(delta.dx).toBe(0);
  });

  it('scrolls back when the target sits above the safe band', () => {
    const delta = computeScrollDelta(rect(10, 20, 300, 80), rect(200, 8, 760, 300));
    expect(delta.dy).toBe(-190);
  });

  it('aligns a target taller than the band to its top edge', () => {
    const delta = computeScrollDelta(rect(300, 20, 300, 400), rect(8, 8, 760, 200));
    expect(delta.dy).toBe(292);
  });

  it('scrolls horizontally for wide tables', () => {
    const delta = computeScrollDelta(rect(20, 900, 300, 40), rect(8, 8, 600, 400));
    expect(delta.dx).toBe(592);
  });
});

describe('docked fallback bounds', () => {
  it('keeps the band inside a panel shorter than the minimum popover height', () => {
    const placement = computePlacement({
      target: rect(10, 10, 50, 20),
      panelWidth: 300,
      panelHeight: 100,
      popoverWidth: 200,
      popoverHeight: 180,
    });

    expect(placement.dock).not.toBe('none');
    expect(placement.top).toBeGreaterThanOrEqual(0);
    expect(placement.top + placement.maxHeight).toBeLessThanOrEqual(100);
  });

  it('keeps the band inside a 60 px panel', () => {
    const placement = computePlacement({
      target: rect(40, 10, 50, 10),
      panelWidth: 240,
      panelHeight: 60,
      popoverWidth: 200,
      popoverHeight: 400,
    });

    expect(placement.top).toBeGreaterThanOrEqual(0);
    expect(placement.top + placement.maxHeight).toBeLessThanOrEqual(60);
  });
});

describe('intersectRects', () => {
  it('returns null for disjoint rects and the shared area otherwise', () => {
    expect(intersectRects(rect(0, 0, 10, 10), rect(20, 20, 5, 5))).toBeNull();
    expect(intersectRects(rect(0, 0, 10, 10), rect(5, 5, 10, 10))).toEqual({
      top: 5,
      left: 5,
      width: 5,
      height: 5,
    });
  });
});

describe('spotlightRect', () => {
  const panel = rect(0, 0, 800, 400);

  it('clips the highlight to the readable band', () => {
    const spot = spotlightRect(rect(0, 0, 800, 400), panel, rect(0, 0, 800, 250));
    expect(spot).toEqual({ top: 0, left: 0, width: 800, height: 250 });
  });

  it('collapses instead of painting under the popover when the band misses the target', () => {
    const spot = spotlightRect(rect(300, 0, 200, 60), panel, rect(0, 0, 800, 100));
    expect(spot.height).toBe(0);
  });

  it('collapses when the target is outside the panel', () => {
    const spot = spotlightRect(rect(500, 0, 200, 60), panel, rect(0, 0, 800, 100));
    expect(spot.height).toBe(0);
  });
});
