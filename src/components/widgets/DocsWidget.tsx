'use client';

import React, { useEffect, useState } from 'react';
import Image from 'next/image';
import { useAtomValue, useSetAtom } from 'jotai';
import {
  activePanelsAtom,
  focusedPanelAtom,
  panelCountAtom,
  tutorialStatusAtom,
} from '@/store/terminalStore';
import { DOCS_INDEX, WIDGET_DOCS, type DocField, type WidgetDoc } from '@/lib/widgetDocs';
import { resolveWidgetPanel } from '@/lib/widgetTours/resolvePanel';
import { requestWidgetTour } from '@/components/widgetTour/WidgetTourController';
import { useWidgetTourSeen } from '@/lib/widgetTours/seen';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function isDocFieldArray(items: DocField[] | string[]): items is DocField[] {
  return items.length > 0 && typeof items[0] === 'object';
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionBlock({
  section,
}: {
  section: { heading: string; body?: string; items?: DocField[] | string[] };
}) {
  return (
    <div className="mb-4">
      <div className="text-terminal-amber font-bold text-[10px] uppercase tracking-widest mb-1 border-b border-terminal-gray/40 pb-0.5">
        {section.heading}
      </div>
      {section.body && (
        <p className="text-blue-200/80 text-[11px] leading-relaxed font-mono">{section.body}</p>
      )}
      {section.items && section.items.length > 0 && (
        <div className="mt-1 space-y-1.5">
          {isDocFieldArray(section.items)
            ? section.items.map((item) => (
                <div key={item.name} className="flex gap-2 text-[11px] font-mono">
                  <span
                    className="text-blue-300 font-bold shrink-0 min-w-[110px] max-w-[140px] truncate"
                    title={item.name}
                  >
                    {item.name}
                  </span>
                  <span className="text-blue-200/70 leading-snug">{item.desc}</span>
                </div>
              ))
            : (section.items as string[]).map((tip, i) => (
                <div
                  key={i}
                  className="flex gap-2 text-[11px] font-mono text-blue-200/70 leading-snug"
                >
                  <span className="text-terminal-amber shrink-0">›</span>
                  <span>{tip}</span>
                </div>
              ))}
        </div>
      )}
    </div>
  );
}

function DocView({
  doc,
  onReplayTour,
}: {
  doc: WidgetDoc;
  onReplayTour: (cmd: string) => void;
}) {
  const [imgError, setImgError] = useState(false);
  const [isZoomed, setIsZoomed] = useState(false);

  useEffect(() => {
    if (!isZoomed) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsZoomed(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isZoomed]);

  return (
    <div
      data-widget-tour="docs-doc-view"
      className="h-full overflow-y-auto px-3 py-2 relative"
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="text-white font-bold text-xs uppercase tracking-widest">
            {doc.command}
            <span className="text-terminal-amber/60 ml-2 font-normal">— {doc.title}</span>
          </div>
          <p className="text-blue-300/90 text-[11px] font-mono mt-1 leading-relaxed">
            {doc.summary}
          </p>
        </div>
        {doc.kind === 'panel' && (
          <button
            type="button"
            data-widget-tour="docs-replay-tour"
            onClick={() => onReplayTour(doc.command)}
            className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-terminal-amber/60 bg-terminal-amber/10 text-terminal-amber hover:bg-terminal-amber hover:text-black transition-colors shrink-0"
          >
            ▸ REPLAY TOUR
          </button>
        )}
      </div>

      {/* Screenshot */}
      {doc.screenshot && (
        <div data-widget-tour="docs-screenshot" className="mb-4">
          {imgError ? (
            <div className="border border-terminal-gray/40 p-4 text-center text-xs text-zinc-300 uppercase">
              SCREENSHOT NOT CAPTURED YET
            </div>
          ) : (
            <div className="cursor-pointer" onClick={() => setIsZoomed(true)}>
              <Image
                src={doc.screenshot.src}
                alt={doc.screenshot.alt}
                width={1400}
                height={900}
                className="w-full h-auto border border-terminal-gray/40"
                unoptimized
                onError={() => setImgError(true)}
              />
              <p className="text-[10px] text-zinc-400 mt-1 italic">
                {doc.screenshot.caption}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Zoom overlay */}
      {isZoomed && doc.screenshot && !imgError && (
        <div
          className="absolute inset-0 z-20 bg-black/95 overflow-auto flex flex-col items-center justify-center p-4 cursor-zoom-out"
          onClick={() => setIsZoomed(false)}
        >
          <Image
            src={doc.screenshot.src}
            alt={doc.screenshot.alt}
            width={1400}
            height={900}
            className="max-w-full max-h-[85%] object-contain border border-terminal-gray/40"
            unoptimized
          />
          <p className="text-xs text-zinc-300 mt-2">{doc.screenshot.caption}</p>
        </div>
      )}

      {/* Sections */}
      <div>
        {doc.sections.map((section, i) => (
          <SectionBlock key={i} section={section} />
        ))}
      </div>
    </div>
  );
}

function IndexView({
  onSelect,
  onReplayTour,
}: {
  onSelect: (cmd: string) => void;
  onReplayTour: (cmd: string) => void;
}) {
  const seenMap = useWidgetTourSeen();

  return (
    <div
      data-widget-tour="docs-index"
      className="h-full overflow-y-auto px-3 py-2"
    >
      <div className="text-terminal-amber font-bold text-[10px] uppercase tracking-widest mb-1 border-b border-terminal-gray/40 pb-0.5">
        Widget Reference
      </div>
      <div className="p-2 mb-3 bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber text-[10px] leading-snug">
        Replay any widget tour here. Keep the widget open in another panel, then click TOUR.
      </div>
      <div className="space-y-1">
        {DOCS_INDEX.map((doc) => {
          const isSeen = Boolean(seenMap[doc.command]);
          return (
            <div
              key={doc.command}
              className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded hover:bg-blue-900/30 transition-colors group"
            >
              <button
                type="button"
                onClick={() => onSelect(doc.command)}
                className="flex items-start gap-3 text-left flex-1 min-w-0"
              >
                <span className="text-terminal-amber font-bold font-mono text-[11px] shrink-0 w-[84px]">
                  {doc.command}
                </span>
                <span className="text-blue-200/70 font-mono text-[11px] leading-snug group-hover:text-blue-200 truncate">
                  {doc.summary.slice(0, 80)}
                  {doc.summary.length > 80 ? '…' : ''}
                </span>
              </button>
              <div className="flex items-center gap-1.5 shrink-0">
                <span
                  className={`text-[9px] px-1 py-0.2 rounded border uppercase font-mono ${
                    isSeen
                      ? 'border-green-500/50 text-green-400 bg-green-950/20'
                      : 'border-zinc-600 text-zinc-300 bg-zinc-800/40'
                  }`}
                >
                  {isSeen ? 'SEEN' : 'NOT RUN'}
                </span>
                {doc.kind === 'panel' && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onReplayTour(doc.command);
                    }}
                    className="px-1.5 py-0.5 text-[9px] font-bold uppercase border border-terminal-amber/40 text-terminal-amber hover:bg-terminal-amber hover:text-black transition-colors"
                  >
                    TOUR
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function DocsWidget() {
  const focusedPanel = useAtomValue(focusedPanelAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  const panelCount = useAtomValue(panelCountAtom);
  const startAppTour = useSetAtom(tutorialStatusAtom);
  const [manualCmd, setManualCmd] = useState<string | null>(null);
  const [missingPanelCmd, setMissingPanelCmd] = useState<string | null>(null);

  // Determine which widget to document:
  // 1. If user clicked a doc entry from the index, show that.
  // 2. Otherwise, show docs for whatever the focused panel is displaying.
  // 3. If the focused panel IS the DOCS panel itself (or unknown), show the index.
  const focusedCmd = activePanels[focusedPanel];
  const isDocsItself = focusedCmd === 'DOCS' || !focusedCmd;

  const displayCmd = manualCmd ?? (isDocsItself ? null : focusedCmd);
  const doc = displayCmd ? WIDGET_DOCS[displayCmd] : null;

  const handleReplayTour = (command: string) => {
    const targetPanelId = resolveWidgetPanel(command, activePanels, panelCount, focusedPanel);
    if (!targetPanelId) {
      setMissingPanelCmd(command);
    } else {
      setMissingPanelCmd(null);
      setManualCmd(command);
      requestWidgetTour({ panelId: targetPanelId, command, mode: 'replay' });
    }
  };

  return (
    <div className="h-full flex flex-col bg-terminal-bg text-terminal-amber relative">
      {/* Missing panel banner */}
      {missingPanelCmd && (
        <div className="px-3 py-1 bg-red-950/80 border-b border-red-600/60 text-red-200 text-xs flex items-center justify-between shrink-0">
          <span>OPEN {missingPanelCmd} IN A PANEL TO REPLAY THIS TOUR</span>
          <button
            type="button"
            onClick={() => setMissingPanelCmd(null)}
            className="text-red-300 hover:text-white font-bold ml-2 px-1"
          >
            ✕
          </button>
        </div>
      )}

      {/* Inner nav bar */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-terminal-gray/40 shrink-0">
        <button
          type="button"
          onClick={() => startAppTour('active')}
          title="Replay the guided terminal app tour"
          className="text-terminal-amber/70 hover:text-terminal-amber text-[10px] font-mono transition-colors shrink-0"
        >
          ▸ APP TOUR
        </button>
        <span className="text-zinc-500 text-[10px]">/</span>
        {doc ? (
          <>
            <button
              type="button"
              onClick={() => {
                setManualCmd(null);
                setMissingPanelCmd(null);
              }}
              className="text-blue-400/70 hover:text-blue-300 text-[10px] font-mono transition-colors"
            >
              ← INDEX
            </button>
            <span className="text-zinc-500 text-[10px]">/</span>
            <span className="text-terminal-amber text-[10px] font-mono font-bold">
              {doc.command}
            </span>
            {!manualCmd && (
              <span className="text-blue-300/40 text-[9px] font-mono ml-1">(auto)</span>
            )}
          </>
        ) : (
          <span className="text-blue-300/50 text-[10px] font-mono">
            {isDocsItself ? 'Focus a panel to auto-load its docs' : `Viewing: ${focusedCmd}`}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        {doc ? (
          <DocView key={doc.command} doc={doc} onReplayTour={handleReplayTour} />
        ) : (
          <IndexView
            onSelect={(cmd) => {
              setManualCmd(cmd);
              setMissingPanelCmd(null);
            }}
            onReplayTour={handleReplayTour}
          />
        )}
      </div>
    </div>
  );
}
