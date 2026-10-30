import type { WidgetTourPlacement } from './types';

export interface TourRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export type TourDock = 'none' | 'top' | 'bottom';

export interface TourPlacement {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
  dock: TourDock;
  /** Panel region that stays readable once the popover is placed. */
  safe: TourRect;
}

export interface TourPlacementInput {
  target: TourRect;
  panelWidth: number;
  panelHeight: number;
  popoverWidth: number;
  popoverHeight: number;
  preference?: WidgetTourPlacement;
}

const GAP = 8;
const EDGE = 8;
const MIN_POPOVER_HEIGHT = 96;
const MIN_POPOVER_WIDTH = 160;

interface Candidate {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
  side: Exclude<WidgetTourPlacement, 'auto'>;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, Math.max(min, max)));
}

function overlaps(a: TourRect, b: TourRect): boolean {
  return (
    a.left < b.left + b.width &&
    a.left + a.width > b.left &&
    a.top < b.top + b.height &&
    a.top + a.height > b.top
  );
}

function candidateFor(
  side: Exclude<WidgetTourPlacement, 'auto'>,
  input: TourPlacementInput,
): Candidate | null {
  const { target, panelWidth, panelHeight, popoverWidth, popoverHeight } = input;
  const width = Math.min(popoverWidth, panelWidth - 2 * EDGE);
  if (width < MIN_POPOVER_WIDTH) return null;

  if (side === 'below' || side === 'above') {
    const maxHeight = Math.min(
      popoverHeight,
      side === 'below' ? panelHeight - (target.top + target.height) - GAP - EDGE : target.top - GAP - EDGE,
    );
    if (maxHeight < MIN_POPOVER_HEIGHT) return null;

    const top =
      side === 'below' ? target.top + target.height + GAP : target.top - GAP - maxHeight;

    return {
      top,
      left: clamp(target.left, EDGE, panelWidth - width - EDGE),
      width,
      maxHeight,
      side,
    };
  }

  const maxHeight = Math.min(popoverHeight, panelHeight - 2 * EDGE);
  if (maxHeight < MIN_POPOVER_HEIGHT) return null;

  const left = side === 'right' ? target.left + target.width + GAP : target.left - width - GAP;
  if (left < EDGE || left + width > panelWidth - EDGE) return null;

  return {
    top: clamp(target.top, EDGE, panelHeight - maxHeight - EDGE),
    left,
    width,
    maxHeight,
    side,
  };
}

function safeFor(candidate: Candidate, panelWidth: number, panelHeight: number): TourRect {
  const innerWidth = Math.max(0, panelWidth - 2 * EDGE);

  if (candidate.side === 'below') {
    return {
      top: EDGE,
      left: EDGE,
      width: innerWidth,
      height: Math.max(0, candidate.top - GAP - EDGE),
    };
  }

  if (candidate.side === 'above') {
    const top = candidate.top + candidate.maxHeight + GAP;
    return { top, left: EDGE, width: innerWidth, height: Math.max(0, panelHeight - top - EDGE) };
  }

  if (candidate.side === 'right') {
    return {
      top: EDGE,
      left: EDGE,
      width: Math.max(0, candidate.left - GAP - EDGE),
      height: Math.max(0, panelHeight - 2 * EDGE),
    };
  }

  const left = candidate.left + candidate.width + GAP;
  return {
    top: EDGE,
    left,
    width: Math.max(0, panelWidth - left - EDGE),
    height: Math.max(0, panelHeight - 2 * EDGE),
  };
}

function docked(input: TourPlacementInput): TourPlacement {
  const { target, panelWidth, panelHeight, popoverHeight } = input;
  const width = Math.max(0, panelWidth - 2 * EDGE);
  const maxHeight = Math.min(popoverHeight, Math.max(MIN_POPOVER_HEIGHT, panelHeight - 2 * EDGE));
  const dockAtTop = target.top + target.height / 2 > panelHeight / 2;
  const top = dockAtTop ? EDGE : panelHeight - maxHeight - EDGE;

  return {
    top,
    left: EDGE,
    width,
    maxHeight,
    dock: dockAtTop ? 'top' : 'bottom',
    safe: dockAtTop
      ? {
          top: top + maxHeight + GAP,
          left: EDGE,
          width,
          height: Math.max(0, panelHeight - (top + maxHeight + GAP) - EDGE),
        }
      : {
          top: EDGE,
          left: EDGE,
          width,
          height: Math.max(0, top - GAP - EDGE),
        },
  };
}

/**
 * Places the tour popover so it never covers the element it explains, when any side
 * has room. Falls back to a full-width band at the panel edge for short panels.
 */
export function computePlacement(input: TourPlacementInput): TourPlacement {
  const order: Exclude<WidgetTourPlacement, 'auto'>[] = ['below', 'above', 'right', 'left'];
  const preference = input.preference && input.preference !== 'auto' ? input.preference : null;
  const sides = preference ? [preference, ...order.filter((side) => side !== preference)] : order;

  for (const side of sides) {
    const candidate = candidateFor(side, input);
    if (!candidate) continue;

    const rect: TourRect = {
      top: candidate.top,
      left: candidate.left,
      width: candidate.width,
      height: candidate.maxHeight,
    };

    if (overlaps(rect, input.target)) continue;

    return {
      top: candidate.top,
      left: candidate.left,
      width: candidate.width,
      maxHeight: candidate.maxHeight,
      dock: 'none',
      safe: safeFor(candidate, input.panelWidth, input.panelHeight),
    };
  }

  return docked(input);
}

/**
 * Scroll needed so the target sits inside the readable band next to the popover.
 * Positive values scroll the content forward.
 */
export function computeScrollDelta(target: TourRect, safe: TourRect): { dx: number; dy: number } {
  let dy = 0;
  let dx = 0;

  if (target.height >= safe.height || target.top < safe.top) {
    dy = target.top - safe.top;
  } else if (target.top + target.height > safe.top + safe.height) {
    dy = target.top + target.height - (safe.top + safe.height);
  }

  if (target.width >= safe.width || target.left < safe.left) {
    dx = target.left - safe.left;
  } else if (target.left + target.width > safe.left + safe.width) {
    dx = target.left + target.width - (safe.left + safe.width);
  }

  return { dx, dy };
}

/** Clip rect `a` to the bounds of rect `b`. Returns null when no area remains. */
export function intersectRects(a: TourRect, b: TourRect): TourRect | null {
  const top = Math.max(a.top, b.top);
  const left = Math.max(a.left, b.left);
  const bottom = Math.min(a.top + a.height, b.top + b.height);
  const right = Math.min(a.left + a.width, b.left + b.width);
  if (bottom <= top || right <= left) return null;
  return { top, left, width: right - left, height: bottom - top };
}

/**
 * Highlight area for a step. When the target is taller than the readable band, show the
 * part that stays visible instead of painting a highlight under the popover.
 */
export function spotlightRect(target: TourRect, panel: TourRect, safe: TourRect): TourRect {
  const inPanel = intersectRects(target, panel);
  if (!inPanel) return target;

  const inSafe = intersectRects(inPanel, safe);
  if (inSafe && inSafe.height >= 12 && inSafe.width >= 12) return inSafe;

  return inPanel;
}
