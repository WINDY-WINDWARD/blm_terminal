'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';

export interface ModelOption {
  id: string;
  label: string;
}

interface ModelComboboxProps {
  value: string;
  options: ModelOption[];
  onChange: (id: string) => void;
  placeholder?: string;
  disabled?: boolean;
  emptyText?: string;
}

/**
 * Searchable single-select dropdown for model pickers.
 * Native <select> has no search; this renders a button + filterable listbox
 * styled for the terminal theme, with keyboard support (up/down/enter/esc).
 */
export function ModelCombobox({
  value,
  options,
  onChange,
  placeholder = 'Select…',
  disabled = false,
  emptyText = 'No models available.',
}: ModelComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) => o.id.toLowerCase().includes(q) || o.label.toLowerCase().includes(q),
    );
  }, [options, query]);

  // Clamp the highlight when the list shrinks (options reload / filter narrows).
  const safeIdx = filtered.length === 0 ? 0 : Math.min(activeIdx, filtered.length - 1);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open ]);

  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.children[safeIdx] as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [open, safeIdx]);

  const selected = options.find((o) => o.id === value);

  const pick = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery('');
  };

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx(safeIdx + 1 >= filtered.length ? 0 : safeIdx + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx(safeIdx - 1 < 0 ? Math.max(filtered.length - 1, 0) : safeIdx - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filtered[safeIdx]) pick(filtered[safeIdx].id);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <div className="flex gap-1">
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            if (!open) {
              setQuery('');
              setActiveIdx(0);
            }
            setOpen((o) => !o);
          }}
          onKeyDown={(e) => {
            if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault();
              setQuery('');
              setActiveIdx(0);
              setOpen(true);
            }
          }}
          className="flex-1 min-w-0 flex items-center justify-between gap-2 bg-terminal-bg border border-terminal-border px-2 py-2 text-terminal-amber text-sm focus:outline-none focus:border-terminal-amber focus:ring-1 focus:ring-terminal-amber transition-colors disabled:opacity-50"
        >
          <span className={`truncate ${selected || value ? '' : 'text-terminal-muted'}`}>
            {selected ? selected.label : value ? `${value} (not in list)` : placeholder}
          </span>
          <span className="text-terminal-muted text-xs shrink-0">▾</span>
        </button>
        {value ? (
          <button
            type="button"
            disabled={disabled}
            title="Clear selection"
            onClick={() => pick('')}
            className="shrink-0 px-2 border border-terminal-border text-terminal-muted hover:text-white hover:border-terminal-muted transition-colors disabled:opacity-50"
          >
            ✕
          </button>
        ) : null}
      </div>
      {open && !disabled ? (
        <div className="absolute z-20 mt-1 w-full border border-terminal-amber bg-terminal-bg shadow-2xl">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIdx(0);
            }}
            onKeyDown={onInputKeyDown}
            placeholder="Search models…"
            className="w-full bg-terminal-bg border-b border-terminal-border px-2 py-1.5 text-terminal-amber text-xs focus:outline-none placeholder:text-terminal-muted"
          />
          <div ref={listRef} className="max-h-48 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-2 py-2 text-terminal-muted text-xs">{emptyText}</div>
            ) : (
              filtered.map((o, i) => (
                <button
                  key={o.id}
                  type="button"
                  onMouseDown={(e) => {
                    // Select before the outside-click handler closes the panel.
                    e.preventDefault();
                    pick(o.id);
                  }}
                  onMouseEnter={() => setActiveIdx(i)}
                  className={`w-full text-left px-2 py-1.5 text-xs truncate transition-colors ${
                    i === safeIdx
                      ? 'bg-terminal-amber text-terminal-bg'
                      : 'text-terminal-amber hover:bg-terminal-amber/20'
                  } ${o.id === value ? 'font-bold' : ''}`}
                  title={o.label}
                >
                  {o.label}
                </button>
              ))
            )}
          </div>
          <div className="px-2 py-1 border-t border-terminal-border text-terminal-muted text-[10px]">
            {filtered.length} of {options.length} models
          </div>
        </div>
      ) : null}
    </div>
  );
}
