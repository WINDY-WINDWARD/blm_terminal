'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAtom } from 'jotai';
import { activeWidgetTourAtom } from '@/store/terminalStore';
import { getWidgetTour } from '@/lib/widgetTours';

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
  top?: number;
  bottom?: number;
  left: number;
  width: number;
  maxHeight: number;
}

export function WidgetTourOverlay({ panelId }: WidgetTourOverlayProps) {
  const [activeTour, setActiveTour] = useAtom(activeWidgetTourAtom);
  const [stepIndex, setStepIndex] = useState(0);

  const popoverRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [targetBox, setTargetBox] = useState<TargetBox | null>(null);
  const [popoverPos, setPopoverPos] = useState<PopoverPos | null>(null);
  const [isAnchorFound, setIsAnchorFound] = useState(false);

  const isActive = activeTour !== null && activeTour.panelId === panelId;
  const definition = isActive && activeTour ? getWidgetTour(activeTour.command) : undefined;
  const steps = definition?.steps ?? [];
  const currentStep = steps[stepIndex];

  const [prevTourKey, setPrevTourKey] = useState<string | null>(null);

  const currentTourKey = activeTour ? `${activeTour.panelId}:${activeTour.command}` : null;
  if (currentTourKey !== prevTourKey) {
    setPrevTourKey(currentTourKey);
    setStepIndex(0);
  }

  const updatePosition = useCallback(() => {
    if (!isActive || !currentStep) return;

    window.requestAnimationFrame(() => {
      const panelEl = document.querySelector<HTMLElement>(`[data-tour-panel-id="${panelId}"]`);
      const overlayEl = overlayRef.current;
      if (!panelEl || !overlayEl) return;

      const panelRect = overlayEl.getBoundingClientRect();
      const targetEl = panelEl.querySelector<HTMLElement>(`[data-widget-tour="${currentStep.anchor}"]`);

      if (!targetEl) {
        setIsAnchorFound(false);
        setTargetBox(null);
        return;
      }

      const initialRect = targetEl.getBoundingClientRect();
      const isOutsidePanel =
        initialRect.top < panelRect.top || initialRect.bottom > panelRect.bottom;
      if (isOutsidePanel) {
        targetEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      }

      const targetRect = targetEl.getBoundingClientRect();
      // Target must have some size and be somewhat visible
      if (targetRect.width === 0 && targetRect.height === 0) {
        setIsAnchorFound(false);
        setTargetBox(null);
        return;
      }

      setIsAnchorFound(true);

      const relTop = Math.max(0, targetRect.top - panelRect.top);
      const relLeft = Math.max(0, targetRect.left - panelRect.left);
      const clampedWidth = Math.min(targetRect.width, panelRect.width - relLeft);
      const clampedHeight = Math.min(targetRect.height, panelRect.height - relTop);

      setTargetBox({
        top: relTop,
        left: relLeft,
        width: clampedWidth,
        height: clampedHeight,
      });

      const popoverWidth = Math.min(300, Math.max(200, panelRect.width - 16));
      const spaceBelow = panelRect.height - (relTop + clampedHeight);
      const spaceAbove = relTop;
      const prefPlacement = currentStep.placement ?? 'auto';

      let chosenTop: number | undefined;
      let chosenBottom: number | undefined;
      const popoverHeightEst = 220;

      if (prefPlacement === 'below' && spaceBelow >= 120) {
        chosenTop = relTop + clampedHeight + 8;
      } else if (prefPlacement === 'above' && spaceAbove >= 120) {
        chosenBottom = panelRect.height - relTop + 8;
      } else if (spaceBelow >= popoverHeightEst) {
        chosenTop = relTop + clampedHeight + 8;
      } else if (spaceAbove >= popoverHeightEst) {
        chosenBottom = panelRect.height - relTop + 8;
      } else if (spaceBelow >= spaceAbove) {
        chosenTop = Math.min(relTop + clampedHeight + 8, panelRect.height - 120);
      } else {
        chosenBottom = 8;
      }

      const clampedLeft = Math.max(8, Math.min(relLeft, panelRect.width - popoverWidth - 8));
      const availableHeight =
        chosenTop !== undefined
          ? panelRect.height - chosenTop - 8
          : chosenBottom !== undefined
            ? panelRect.height - chosenBottom - 8
            : panelRect.height - 32;
      const maxHeight = Math.max(120, Math.min(panelRect.height - 16, availableHeight));

      setPopoverPos({
        top: chosenTop,
        bottom: chosenBottom,
        left: clampedLeft,
        width: popoverWidth,
        maxHeight,
      });
    });
  }, [isActive, currentStep, panelId]);

  // Position listeners
  useEffect(() => {
    if (!isActive || !currentStep) return;

    updatePosition();

    const panelEl = document.querySelector<HTMLElement>(`[data-tour-panel-id="${panelId}"]`);
    const overlayEl = overlayRef.current;
    const targetEl = panelEl?.querySelector<HTMLElement>(`[data-widget-tour="${currentStep.anchor}"]`);

    const ro = new ResizeObserver(() => {
      updatePosition();
    });

    if (overlayEl) ro.observe(overlayEl);
    else if (panelEl) ro.observe(panelEl);
    if (targetEl) ro.observe(targetEl);

    const onResize = () => updatePosition();
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);

    return () => {
      ro.disconnect();
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
    };
  }, [isActive, currentStep, panelId, updatePosition]);

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
        className="absolute z-50 bg-[#121212] border border-terminal-amber text-terminal-amber shadow-2xl flex flex-col focus:outline-none"
        style={
          isAnchorFound && popoverPos
            ? {
                top: popoverPos.top !== undefined ? `${popoverPos.top}px` : undefined,
                bottom: popoverPos.bottom !== undefined ? `${popoverPos.bottom}px` : undefined,
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
