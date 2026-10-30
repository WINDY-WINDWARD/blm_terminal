'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAtom } from 'jotai';
import { activeWidgetTourAtom } from '@/store/terminalStore';
import { getWidgetTour } from '@/lib/widgetTours';
import { computePlacement, computeScrollDelta, spotlightRect } from '@/lib/widgetTours/placement';
import type { TourRect } from '@/lib/widgetTours/placement';
import type { WidgetTourStep } from '@/lib/widgetTours/types';

export interface WidgetTourOverlayProps {
  panelId: string;
}

interface TargetBox {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface PopoverPos {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
  dock: 'none' | 'top' | 'bottom';
}

const ANCHOR_TIMEOUT_MS = 2000;
const ACTION_SETTLE_MS = 60;
const MIN_POPOVER_WIDTH = 200;
const MAX_POPOVER_WIDTH = 320;

/**
 * Definitions may pass either a CSS selector or a bare click id such as
 * `tab-bulk`. Normalise both to the attribute selector the widgets expose.
 */
function toClickSelector(value: string): string {
  return value.includes('[') ? value : `[data-widget-tour-click="${value}"]`;
}

function getPanel(panelId: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-tour-panel-id="${panelId}"]`);
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function findScroller(from: HTMLElement, boundary: HTMLElement): HTMLElement | null {
  let node = from.parentElement;

  while (node && node !== boundary) {
    const style = window.getComputedStyle(node);
    const canScrollY =
      /(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1;
    const canScrollX =
      /(auto|scroll)/.test(style.overflowX) && node.scrollWidth > node.clientWidth + 1;
    if (canScrollY || canScrollX) return node;
    node = node.parentElement;
  }

  return null;
}

export function WidgetTourOverlay({ panelId }: WidgetTourOverlayProps) {
  const [activeTour, setActiveTour] = useAtom(activeWidgetTourAtom);
  const [stepIndex, setStepIndex] = useState(0);

  const popoverRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const targetElRef = useRef<HTMLElement | null>(null);
  const restoreRef = useRef<HTMLElement[]>([]);
  const popoverHeightRef = useRef(180);

  const [targetBox, setTargetBox] = useState<TargetBox | null>(null);
  const [popoverPos, setPopoverPos] = useState<PopoverPos | null>(null);
  const [isAnchorFound, setIsAnchorFound] = useState(false);
  const [popoverHeight, setPopoverHeight] = useState(180);

  const isActive = activeTour !== null && activeTour.panelId === panelId;
  const definition = isActive && activeTour ? getWidgetTour(activeTour.command) : undefined;
  const steps = definition?.steps ?? [];
  const currentStep: WidgetTourStep | undefined = steps[stepIndex];

  const [prevTourKey, setPrevTourKey] = useState<string | null>(null);

  const currentTourKey = activeTour ? `${activeTour.panelId}:${activeTour.command}` : null;
  if (currentTourKey !== prevTourKey) {
    setPrevTourKey(currentTourKey);
    setStepIndex(0);
  }

  popoverHeightRef.current = popoverHeight;

  const positionStep = useCallback(
    async (targetEl: HTMLElement, step: WidgetTourStep, scroll: boolean) => {
      const overlayEl = overlayRef.current;
      if (!overlayEl) return;

      const panelRect = overlayEl.getBoundingClientRect();
      const panel: TourRect = { top: 0, left: 0, width: panelRect.width, height: panelRect.height };
      const toRect = (rect: DOMRect): TourRect => ({
        top: rect.top - panelRect.top,
        left: rect.left - panelRect.left,
        width: rect.width,
        height: rect.height,
      });

      const popoverWidth = Math.max(
        MIN_POPOVER_WIDTH,
        Math.min(MAX_POPOVER_WIDTH, panelRect.width - 16),
      );

      const measure = () =>
        computePlacement({
          target: toRect(targetEl.getBoundingClientRect()),
          panelWidth: panelRect.width,
          panelHeight: panelRect.height,
          popoverWidth,
          popoverHeight: popoverHeightRef.current,
          preference: step.placement,
        });

      let placement = measure();

      if (scroll) {
        const panelEl = getPanel(panelId);
        const scroller = panelEl ? findScroller(targetEl, panelEl) : null;
        if (scroller) {
          const { dx, dy } = computeScrollDelta(toRect(targetEl.getBoundingClientRect()), placement.safe);
          if (dx !== 0 || dy !== 0) {
            scroller.scrollBy({ left: dx, top: dy, behavior: 'auto' });
            await nextFrame();
            await nextFrame();
            placement = measure();
          }
        }
      }

      const target = spotlightRect(toRect(targetEl.getBoundingClientRect()), panel, placement.safe);
      setTargetBox(target);
      setPopoverPos({
        top: placement.top,
        left: placement.left,
        width: placement.width,
        maxHeight: placement.maxHeight,
        dock: placement.dock,
      });
    },
    [panelId],
  );

  // Remember the sub-view the widget was showing, so the tour can put it back.
  useEffect(() => {
    if (!isActive) return;

    const panelEl = getPanel(panelId);
    restoreRef.current = panelEl
      ? Array.from(
          panelEl.querySelectorAll<HTMLElement>(
            '[data-widget-tour-click][aria-selected="true"], [data-widget-tour-click][data-tour-active="true"]',
          ),
        )
      : [];

    return () => {
      for (const el of restoreRef.current) {
        if (el.isConnected) el.click();
      }
      restoreRef.current = [];
    };
  }, [isActive, panelId]);

  // Undo a view the tour opened, such as a doc page returning to the index.
  useEffect(() => {
    if (!isActive || !definition?.restoreActions?.length) return;

    return () => {
      const panelEl = getPanel(panelId);
      for (const click of definition.restoreActions ?? []) {
        panelEl?.querySelector<HTMLElement>(toClickSelector(click.selector))?.click();
      }
    };
  }, [isActive, panelId, definition]);

  // Run the definition's opening clicks once per tour.
  useEffect(() => {
    if (!isActive || !definition) return;

    const panelEl = getPanel(panelId);
    for (const click of definition.startActions ?? []) {
      panelEl?.querySelector<HTMLElement>(toClickSelector(click.selector))?.click();
    }
    // Only re-run when a new tour starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, activeTour?.command, panelId]);

  // Prepare each step: run its clicks, wait for the anchor, scroll it into the free band.
  useEffect(() => {
    if (!isActive || !currentStep) return;

    let cancelled = false;
    setIsAnchorFound(false);
    setTargetBox(null);
    setPopoverPos(null);
    targetElRef.current = null;

    const run = async () => {
      const panelEl = getPanel(panelId);
      if (!panelEl) return;

      for (const click of currentStep.actions ?? []) {
        const el = panelEl.querySelector<HTMLElement>(toClickSelector(click.selector));
        if (!el) continue;
        if (el.getAttribute('data-tour-active') === 'true') continue;
        el.click();
        await wait(ACTION_SETTLE_MS);
      }

      const startedAt = performance.now();
      let targetEl: HTMLElement | null = null;
      while (!cancelled) {
        const candidate = panelEl.querySelector<HTMLElement>(
          `[data-widget-tour="${currentStep.anchor}"]`,
        );
        if (candidate) {
          const rect = candidate.getBoundingClientRect();
          if (rect.width > 0 || rect.height > 0) {
            targetEl = candidate;
            break;
          }
        }
        if (performance.now() - startedAt > ANCHOR_TIMEOUT_MS) break;
        await nextFrame();
        await wait(40);
      }

      if (cancelled) return;

      if (!targetEl) {
        if (stepIndex < steps.length - 1) {
          setStepIndex(stepIndex + 1);
        } else {
          setActiveTour(null);
        }
        return;
      }

      targetElRef.current = targetEl;
      await positionStep(targetEl, currentStep, true);
      if (!cancelled) setIsAnchorFound(true);
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [isActive, currentStep, panelId, positionStep, stepIndex, steps.length, setActiveTour]);

  // Follow panel and target size changes without moving the page under the user.
  useEffect(() => {
    if (!isActive || !currentStep) return;

    const overlayEl = overlayRef.current;
    const resizeObserver = new ResizeObserver(() => {
      const targetEl = targetElRef.current;
      if (targetEl) void positionStep(targetEl, currentStep, false);
    });

    if (overlayEl) resizeObserver.observe(overlayEl);
    const targetEl = targetElRef.current;
    if (targetEl) resizeObserver.observe(targetEl);

    return () => resizeObserver.disconnect();
  }, [isActive, currentStep, positionStep]);

  // Measure the real popover height so the placement uses accurate space.
  useEffect(() => {
    const el = popoverRef.current;
    if (!el) return;
    const measured = el.offsetHeight;
    if (measured > 0 && Math.abs(measured - popoverHeightRef.current) > 4) {
      setPopoverHeight(measured);
      const targetEl = targetElRef.current;
      if (targetEl && currentStep) void positionStep(targetEl, currentStep, false);
    }
  });

  // Focus popover on step change
  useEffect(() => {
    if (isActive) {
      popoverRef.current?.focus();
    }
  }, [isActive, stepIndex]);

  // Return focus to the element that had it before the tour started
  useEffect(() => {
    if (!isActive) return;
    const previous = document.activeElement as HTMLElement | null;
    return () => {
      if (previous && previous.isConnected) {
        previous.focus();
      }
    };
  }, [isActive]);

  // Keyboard navigation and Tab trap
  useEffect(() => {
    if (!isActive || steps.length === 0) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        setActiveTour(null);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        e.stopPropagation();
        if (stepIndex < steps.length - 1) {
          setStepIndex((i) => i + 1);
        } else {
          setActiveTour(null);
        }
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        e.stopPropagation();
        if (stepIndex > 0) {
          setStepIndex((i) => i - 1);
        }
      } else if (e.key === 'Tab') {
        if (!popoverRef.current) return;
        const focusables = popoverRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;

        const first = focusables[0];
        const last = focusables[focusables.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [isActive, steps.length, stepIndex, setActiveTour]);

  if (!isActive || steps.length === 0 || !currentStep) {
    return null;
  }

  const isLastStep = stepIndex === steps.length - 1;

  const handleNext = () => {
    if (isLastStep) {
      setActiveTour(null);
    } else {
      setStepIndex((i) => i + 1);
    }
  };

  const handleBack = () => {
    if (stepIndex > 0) {
      setStepIndex((i) => i - 1);
    }
  };

  const handleSkip = () => {
    setActiveTour(null);
  };

  return (
    <div
      ref={overlayRef}
      className="absolute inset-0 z-40 overflow-hidden font-mono select-none"
      data-widget-tour-overlay=""
      data-tour-dock={popoverPos?.dock ?? 'none'}
    >
      {/* Dimmed backdrop or cutout */}
      {isAnchorFound && targetBox ? (
        <div
          className="absolute border border-terminal-amber pointer-events-none transition-all duration-150"
          style={{
            top: targetBox.top,
            left: targetBox.left,
            width: targetBox.width,
            height: targetBox.height,
            boxShadow: '0 0 0 9999px rgba(0,0,0,0.78)',
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-black/80" />
      )}

      {/* Popover Card */}
      <div
        ref={popoverRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={currentStep.title}
        data-tour-popover=""
        className="absolute z-50 bg-[#121212] border border-terminal-amber text-terminal-amber shadow-2xl flex flex-col focus:outline-none"
        style={
          isAnchorFound && popoverPos
            ? {
                top: `${popoverPos.top}px`,
                left: `${popoverPos.left}px`,
                width: `${popoverPos.width}px`,
                maxHeight: `${popoverPos.maxHeight}px`,
              }
            : {
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                width: 'min(300px, calc(100% - 16px))',
                maxHeight: 'calc(100% - 32px)',
                visibility: 'hidden',
              }
        }
      >
        {/* Header */}
        <div className="px-3 py-1.5 border-b border-terminal-border/60 bg-terminal-card/80 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-terminal-amber/70 font-bold">
              STEP {stepIndex + 1} OF {steps.length}
            </span>
          </div>
          <button
            type="button"
            onClick={handleSkip}
            title="Close tour (Esc)"
            className="text-xs text-white/50 hover:text-white px-1 leading-none transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Title */}
        <div className="px-3 pt-2 pb-1 font-bold text-xs text-white uppercase tracking-wide shrink-0">
          {currentStep.title}
        </div>

        {/* Body */}
        <div className="px-3 py-1 text-[11px] leading-relaxed text-zinc-200 overflow-y-auto flex-1 select-text">
          {currentStep.body}
        </div>

        {/* Footer */}
        <div className="px-3 pt-2 pb-2 border-t border-terminal-border/60 bg-terminal-card/40 flex flex-col gap-1.5 shrink-0">
          <div className="flex items-center justify-between gap-1">
            <button
              type="button"
              onClick={handleBack}
              disabled={stepIndex === 0}
              className="px-2 py-0.5 text-[10px] font-bold uppercase border border-terminal-border text-white/70 hover:text-white hover:border-terminal-amber/60 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            >
              Back
            </button>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={handleSkip}
                className="px-2 py-0.5 text-[10px] font-bold uppercase text-white/60 hover:text-white transition-colors"
              >
                Skip
              </button>
              <button
                type="button"
                onClick={handleNext}
                className="px-2.5 py-0.5 text-[10px] font-bold uppercase bg-terminal-amber text-black hover:bg-terminal-amber/90 transition-colors"
              >
                {isLastStep ? 'Finish' : 'Next'}
              </button>
            </div>
          </div>
          <p className="text-[9px] leading-tight text-white/55 text-center">
            Replay from DOCS: keep both panels open, then click REPLAY TOUR.
          </p>
        </div>
      </div>
    </div>
  );
}
