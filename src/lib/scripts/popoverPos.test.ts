import { describe, expect, it } from 'vitest';
import { computePopoverPos } from './popoverPos';

const VP = { width: 1280, height: 800 };

describe('computePopoverPos', () => {
  it('left-aligns below the button in open space', () => {
    expect(
      computePopoverPos({ top: 100, bottom: 120, left: 50, right: 90 }, VP),
    ).toEqual({ top: 122, left: 50 });
  });

  it('flips to right-anchored when left-anchored would overflow', () => {
    // left(1100) + 288 > 1280 → anchor right edge to button right.
    expect(
      computePopoverPos({ top: 100, bottom: 120, left: 1100, right: 1140 }, VP),
    ).toEqual({ top: 122, left: 852 });
  });

  it('flips above when there is no room below', () => {
    // bottom(780) + 2 + 384 > 800 → above.
    expect(
      computePopoverPos({ top: 760, bottom: 780, left: 50, right: 90 }, VP),
    ).toEqual({ top: 374, left: 50 });
  });

  it('clamps into the viewport for oversized popovers / tiny viewports', () => {
    // Popover taller than the viewport: top clamps to MARGIN, not negative.
    expect(
      computePopoverPos({ top: 100, bottom: 120, left: 50, right: 90 }, { width: 200, height: 300 }),
    ).toEqual({ top: 8, left: 8 });
  });
});
