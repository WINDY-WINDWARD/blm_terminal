/**
 * BLM Script Lab v1 — popover anchor math (pure, tested).
 *
 * The Scripts popover is portaled to document.body with `position: fixed`,
 * so it escapes the chart Panel's `overflow-hidden` clipping. This module
 * computes its top/left from the anchor button rect: prefer below + left-
 * aligned, flip to right-anchored when it would run off the viewport, flip
 * above when there is no room below, always clamped to viewport margins.
 */

export interface RectLike {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface ViewportLike {
  width: number;
  height: number;
}

export interface PopoverPos {
  top: number;
  left: number;
}

export const POPOVER_WIDTH = 288; // w-72
export const POPOVER_MAX_HEIGHT = 384; // max-h-96
const GAP = 2;
const MARGIN = 8;

export function computePopoverPos(
  button: RectLike,
  viewport: ViewportLike,
  popoverWidth: number = POPOVER_WIDTH,
  popoverHeight: number = POPOVER_MAX_HEIGHT,
): PopoverPos {
  // Horizontal: left-align, flip to right-anchored on overflow, clamp.
  let left = button.left;
  if (left + popoverWidth > viewport.width - MARGIN) {
    left = button.right - popoverWidth;
  }
  left = Math.max(MARGIN, Math.min(left, viewport.width - popoverWidth - MARGIN));

  // Vertical: below the button, flip above when no room, clamp.
  let top = button.bottom + GAP;
  if (top + popoverHeight > viewport.height - MARGIN) {
    top = button.top - popoverHeight - GAP;
  }
  top = Math.max(MARGIN, Math.min(top, viewport.height - popoverHeight - MARGIN));

  return { top: Math.round(top), left: Math.round(left) };
}
