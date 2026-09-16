'use client';

import React, { useState } from 'react';
import { useAtomValue, useSetAtom } from 'jotai';
import { focusedPanelAtom, activePanelsAtom, tutorialStatusAtom } from '@/store/terminalStore';
import { WIDGET_DOCS, DOCS_INDEX, type WidgetDoc, type DocField } from '@/lib/widgetDocs';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function isDocFieldArray(items: DocField[] | string[]): items is DocField[] {
  return items.length > 0 && typeof items[0] === 'object';
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionBlock({ section }: { section: { heading: string; body?: string; items?: DocField[] | string[] } }) {
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
                  <span className="text-blue-300 font-bold shrink-0 min-w-[110px] max-w-[140px] truncate" title={item.name}>
                    {item.name}
                  </span>
                  <span className="text-blue-200/70 leading-snug">{item.desc}</span>
                </div>
              ))
            : (section.items as string[]).map((tip, i) => (
                <div key={i} className="flex gap-2 text-[11px] font-mono text-blue-200/70 leading-snug">
                  <span className="text-terminal-amber shrink-0">›</span>
                  <span>{tip}</span>
                </div>
              ))}
        </div>
      )}
    </div>
  );
}

function DocView({ doc }: { doc: WidgetDoc }) {
  return (
    <div className="h-full overflow-y-auto px-3 py-2 scrollbar-thin scrollbar-thumb-terminal-gray">
      {/* Header */}
      <div className="mb-3">
        <div className="text-white font-bold text-xs uppercase tracking-widest">
          {doc.command}
          <span className="text-terminal-amber/60 ml-2 font-normal">— {doc.title}</span>
        </div>
        <p className="text-blue-300/90 text-[11px] font-mono mt-1 leading-relaxed">{doc.summary}</p>
      </div>

      {/* Sections */}
      <div>
        {doc.sections.map((section, i) => (
          <SectionBlock key={i} section={section} />
        ))}
      </div>
    </div>
  );
}

function IndexView({ onSelect }: { onSelect: (cmd: string) => void }) {
  return (
    <div className="h-full overflow-y-auto px-3 py-2 scrollbar-thin scrollbar-thumb-terminal-gray">
      <div className="text-terminal-amber font-bold text-[10px] uppercase tracking-widest mb-2 border-b border-terminal-gray/40 pb-0.5">
        Widget Reference
      </div>
      <p className="text-blue-200/70 text-[11px] font-mono mb-3 leading-relaxed">
        Click any widget to read its documentation, or focus a panel to auto-navigate here.
      </p>
      <div className="space-y-1">
        {DOCS_INDEX.map((doc) => (
          <button
            key={doc.command}
            onClick={() => onSelect(doc.command)}
            className="w-full flex items-start gap-3 px-2 py-1.5 rounded text-left hover:bg-blue-900/30 transition-colors group"
          >
            <span className="text-terminal-amber font-bold font-mono text-[11px] shrink-0 w-[80px]">
              {doc.command}
            </span>
            <span className="text-blue-200/70 font-mono text-[11px] leading-snug group-hover:text-blue-200">
              {doc.summary.slice(0, 80)}{doc.summary.length > 80 ? '…' : ''}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function DocsWidget() {
  const focusedPanel = useAtomValue(focusedPanelAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  const startTour = useSetAtom(tutorialStatusAtom);
  const [manualCmd, setManualCmd] = useState<string | null>(null);

  // Determine which widget to document:
  // 1. If user clicked a doc entry from the index, show that.
  // 2. Otherwise, show docs for whatever the focused panel is displaying.
  // 3. If the focused panel IS the DOCS panel itself (or unknown), show the index.
  const focusedCmd = activePanels[focusedPanel];
  const isDocsItself = focusedCmd === 'DOCS' || !focusedCmd;

  const displayCmd = manualCmd ?? (isDocsItself ? null : focusedCmd);
  const doc = displayCmd ? WIDGET_DOCS[displayCmd] : null;

  return (
    <div className="h-full flex flex-col bg-terminal-bg text-terminal-amber">
      {/* Inner nav bar */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-terminal-gray/40 shrink-0">
        <button
          onClick={() => startTour('active')}
          title="Replay the guided tour"
          className="text-terminal-amber/70 hover:text-terminal-amber text-[10px] font-mono transition-colors shrink-0"
        >
          ▸ TOUR
        </button>
        <span className="text-terminal-gray/40 text-[10px]">/</span>
        {doc ? (
          <>
            <button
              onClick={() => setManualCmd(null)}
              className="text-blue-400/70 hover:text-blue-300 text-[10px] font-mono transition-colors"
            >
              ← INDEX
            </button>
            <span className="text-terminal-gray/40 text-[10px]">/</span>
            <span className="text-terminal-amber text-[10px] font-mono font-bold">{doc.command}</span>
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
      <div className="flex-1 overflow-hidden">
        {doc ? (
          <DocView doc={doc} />
        ) : (
          <IndexView onSelect={(cmd) => setManualCmd(cmd)} />
        )}
      </div>
    </div>
  );
}
