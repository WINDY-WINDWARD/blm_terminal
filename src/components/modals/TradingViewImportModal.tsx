'use client';

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSetAtom } from 'jotai';
import {
  Upload,
  Link as LinkIcon,
  Clipboard,
  Check,
  AlertTriangle,
  X,
  FileText,
  Loader2,
  Layers,
  ArrowRight,
  Filter,
} from 'lucide-react';
import {
  parseTradingViewList,
  resolveImportPreview,
  buildImportPayload,
  type TradingViewParseResult,
} from '@/lib/tradingviewImport';
import { layoutToastAtom, type Watchlist } from '@/store/terminalStore';

interface TradingViewImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (targetWatchlistId: number) => void;
  watchlists: Watchlist[];
  activeWatchlistId: number;
}

type ImportTab = 'upload' | 'paste' | 'link';
type ImportMode = 'create' | 'append' | 'replace';

export function TradingViewImportModal({
  isOpen,
  onClose,
  onSuccess,
  watchlists,
  activeWatchlistId,
}: TradingViewImportModalProps) {
  const queryClient = useQueryClient();
  const setLayoutToast = useSetAtom(layoutToastAtom);

  const [activeTab, setActiveTab] = useState<ImportTab>('upload');

  const [pastedText, setPastedText] = useState('');
  const [urlInput, setUrlInput] = useState('https://in.tradingview.com/watchlists/115430006/');
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileRawText, setFileRawText] = useState<string>('');

  const [importMode, setImportMode] = useState<ImportMode>('create');
  const [baseName, setBaseName] = useState('TV Watchlist');
  const [splitSections, setSplitSections] = useState(false);
  const [targetId, setTargetId] = useState<number>(activeWatchlistId || (watchlists[0]?.id ?? 1));

  const [filterText, setFilterText] = useState('');
  const [userExcludedIds, setUserExcludedIds] = useState<Set<string>>(new Set());

  const [fetchError, setFetchError] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (activeWatchlistId && watchlists.some((w) => w.id === activeWatchlistId)) {
      setTargetId(activeWatchlistId);
    } else if (watchlists.length > 0) {
      setTargetId(watchlists[0].id);
    }
  }, [activeWatchlistId, watchlists]);

  const rawInput = useMemo(() => {
    if (activeTab === 'upload') return fileRawText;
    if (activeTab === 'paste') return pastedText;
    return '';
  }, [activeTab, fileRawText, pastedText]);

  const parseResult: TradingViewParseResult = useMemo(() => {
    return parseTradingViewList(rawInput);
  }, [rawInput]);

  useEffect(() => {
    setUserExcludedIds(new Set());
  }, [rawInput]);

  const { data: targetItemsData } = useQuery({
    queryKey: ['watchlist-items', targetId],
    queryFn: async () => {
      const res = await fetch(`/api/py/watchlists/${targetId}/items`);
      if (!res.ok) return [];
      return (await res.json()) as Array<{ id: number; symbol: string; exchange: string }>;
    },
    enabled: isOpen && importMode === 'append' && !!targetId,
  });

  const targetExistingSymbols = useMemo(() => {
    return (targetItemsData || []).map((it) => it.symbol);
  }, [targetItemsData]);

  const targetCurrentCount = targetItemsData?.length ?? 0;

  const resolution = useMemo(() => {
    return resolveImportPreview(parseResult, {
      mode: importMode,
      splitSections,
      targetWatchlistExistingSymbols: targetExistingSymbols,
      targetWatchlistCurrentCount: targetCurrentCount,
      userExcludedIds,
    });
  }, [parseResult, importMode, splitSections, targetExistingSymbols, targetCurrentCount, userExcludedIds]);

  const fetchUrlMutation = useMutation({
    mutationFn: async (url: string) => {
      setFetchError(null);
      const res = await fetch('/api/py/watchlists/import-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.error || `Failed to fetch URL (HTTP ${res.status})`);
      }
      return (await res.json()) as { source_name: string; raw_symbols: string[] };
    },
    onSuccess: (data) => {
      if (data.source_name) {
        const cleanName = data.source_name.replace(/[^A-Za-z0-9 _-]/g, '').trim().slice(0, 32);
        if (cleanName) {
          setBaseName(cleanName);
        }
      }
      const joined = data.raw_symbols.join('\n');
      setPastedText(joined);
      setActiveTab('paste');
      setFetchError(null);
    },
    onError: (err: Error) => {
      setFetchError(err.message);
    },
  });

  const importMutation = useMutation({
    mutationFn: async () => {
      setImportError(null);

      const payload = buildImportPayload(resolution, {
        baseName,
        mode: importMode,
        splitSections,
        targetWatchlistId: targetId,
      });

      const res = await fetch('/api/py/watchlists/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.error || `Import failed (HTTP ${res.status})`);
      }

      return await res.json();
    },
    onSuccess: (data) => {
      const finalId = data.target_watchlist_id || (data.created_watchlists?.[0]?.id ?? targetId);
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      if (finalId) {
        queryClient.invalidateQueries({ queryKey: ['watchlist', finalId] });
        queryClient.invalidateQueries({ queryKey: ['watchlist-items', finalId] });
      }

      const skippedCount = data.skipped_symbols?.length || 0;
      const skippedMsg = skippedCount > 0 ? ` (${skippedCount} skipped)` : '';

      setLayoutToast({
        visible: true,
        message: `Imported ${data.total_imported} symbol${data.total_imported === 1 ? '' : 's'}${skippedMsg}`,
        type: 'success',
        source: 'Watchlist',
      });

      onSuccess(finalId);
      onClose();
    },
    onError: (err: Error) => {
      setImportError(err.message);
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    readUploadedFile(file);
  };

  const readUploadedFile = (file: File) => {
    setFileName(file.name);
    const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '').replace(/[^A-Za-z0-9 _-]/g, '').trim();
    if (nameWithoutExt) {
      setBaseName(nameWithoutExt.slice(0, 32));
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      setFileRawText(content || '');
    };
    reader.readAsText(file);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      readUploadedFile(file);
    }
  };

  const toggleItemSelection = (id: string) => {
    setUserExcludedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const selectAllValid = () => {
    setUserExcludedIds(new Set());
  };

  const deselectAll = () => {
    const allIds = new Set<string>();
    for (const item of parseResult.items) {
      if (item.isValidNse) {
        allIds.add(item.id);
      }
    }
    setUserExcludedIds(allIds);
  };

  const filteredPreviewItems = useMemo(() => {
    if (!filterText.trim()) return resolution.items;
    const term = filterText.trim().toUpperCase();
    return resolution.items.filter(
      (item) => item.symbol.includes(term) || item.section.toUpperCase().includes(term)
    );
  }, [resolution.items, filterText]);

  const isBaseNameValid =
    importMode !== 'create' ||
    (/^[A-Za-z0-9 _-]+$/.test(baseName.trim()) && baseName.trim().length <= 32);

  const canSubmit =
    resolution.canSubmit &&
    isBaseNameValid &&
    !importMutation.isPending;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl bg-[#09090b] border border-[#27272a] rounded-lg shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Bento Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#27272a] bg-[#121216]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold tracking-wider text-white uppercase font-mono">
                TradingView Watchlist Import
              </h2>
              <p className="text-[11px] text-zinc-400 font-sans">
                Import symbols from TradingView export files, clipboard text, or public shared links.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-1 px-5 pt-3 border-b border-[#27272a] bg-[#0c0c0f]">
          <button
            onClick={() => setActiveTab('upload')}
            className={`flex items-center gap-2 px-3 py-2 text-xs font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'upload'
                ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/5'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Upload className="w-3.5 h-3.5" />
            FILE UPLOAD (.TXT / .CSV)
          </button>
          <button
            onClick={() => setActiveTab('paste')}
            className={`flex items-center gap-2 px-3 py-2 text-xs font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'paste'
                ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/5'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Clipboard className="w-3.5 h-3.5" />
            PASTE SYMBOLS
          </button>
          <button
            onClick={() => setActiveTab('link')}
            className={`flex items-center gap-2 px-3 py-2 text-xs font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'link'
                ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/5'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <LinkIcon className="w-3.5 h-3.5" />
            SHARED URL
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* TAB 1: FILE UPLOAD */}
          {activeTab === 'upload' && (
            <div
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-[#27272a] hover:border-terminal-amber/60 bg-[#121216] rounded-lg p-6 flex flex-col items-center justify-center text-center cursor-pointer transition-colors"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.csv"
                onChange={handleFileChange}
                className="hidden"
              />
              <div className="p-3 bg-zinc-900 border border-zinc-800 rounded-full mb-3 text-terminal-amber">
                <FileText className="w-6 h-6" />
              </div>
              <div className="text-xs font-bold text-white mb-1 uppercase font-mono">
                {fileName ? fileName : 'Click or drop TradingView export file'}
              </div>
              <p className="text-[11px] text-zinc-400 max-w-sm">
                Supports TradingView comma-delimited export files (.txt, .csv) with optional section headers.
              </p>
              {fileRawText && (
                <div className="mt-3 text-[11px] text-emerald-400 font-mono">
                  ✓ File loaded ({parseResult.summary.totalParsed} symbols parsed)
                </div>
              )}
            </div>
          )}

          {/* TAB 2: PASTE LIST */}
          {activeTab === 'paste' && (
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-[11px] text-zinc-400">
                <span>Paste symbols or TradingView section headers (e.g. ### BANKING)</span>
                <span>{parseResult.summary.totalParsed} symbols detected</span>
              </div>
              <textarea
                value={pastedText}
                onChange={(e) => setPastedText(e.target.value)}
                placeholder="NSE:RELIANCE, NSE:TCS, NSE:INFY&#10;### BANKING&#10;NSE:HDFCBANK, NSE:ICICIBANK"
                rows={5}
                className="w-full bg-[#121216] border border-[#27272a] focus:border-terminal-amber text-zinc-200 text-xs font-mono p-3 rounded outline-none transition-colors"
              />
            </div>
          )}

          {/* TAB 3: SHARED URL */}
          {activeTab === 'link' && (
            <div className="space-y-3 bg-[#121216] border border-[#27272a] p-4 rounded-lg">
              <div>
                <label className="block text-xs font-bold text-zinc-300 uppercase mb-1">
                  TradingView Shared Watchlist Link
                </label>
                <div className="text-[11px] text-zinc-400 mb-2">
                  Enter a public TradingView watchlist URL (e.g. https://in.tradingview.com/watchlists/115430006/)
                </div>
                <div className="flex gap-2">
                  <input
                    type="url"
                    value={urlInput}
                    onChange={(e) => setUrlInput(e.target.value)}
                    placeholder="https://in.tradingview.com/watchlists/..."
                    className="flex-1 bg-[#1a1a22] border border-[#27272a] focus:border-terminal-amber text-white text-xs px-3 py-2 rounded outline-none font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => fetchUrlMutation.mutate(urlInput)}
                    disabled={fetchUrlMutation.isPending || !urlInput.trim()}
                    className="flex items-center gap-1.5 px-4 py-2 bg-terminal-amber hover:bg-amber-400 text-black font-bold rounded text-xs disabled:opacity-40 transition-colors cursor-pointer"
                  >
                    {fetchUrlMutation.isPending ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        FETCHING...
                      </>
                    ) : (
                      <>
                        <ArrowRight className="w-3.5 h-3.5" />
                        FETCH
                      </>
                    )}
                  </button>
                </div>
              </div>

              {fetchError && (
                <div className="p-3 bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs rounded flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                  <span>{fetchError}</span>
                </div>
              )}
            </div>
          )}

          {/* Import Destination & Configuration Bento Card */}
          <div className="bg-[#121216] border border-[#27272a] p-4 rounded-lg space-y-4">
            <div className="text-xs font-bold text-terminal-amber uppercase tracking-wider font-mono">
              Import Settings
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Import Mode */}
              <div>
                <label className="block text-[11px] text-zinc-400 uppercase mb-1">Mode</label>
                <select
                  value={importMode}
                  onChange={(e) => setImportMode(e.target.value as ImportMode)}
                  className="w-full bg-[#18181f] border border-[#27272a] text-white text-xs px-2.5 py-1.5 rounded outline-none focus:border-terminal-amber"
                >
                  <option value="create">CREATE NEW WATCHLIST</option>
                  <option value="append">APPEND TO EXISTING</option>
                  <option value="replace">REPLACE EXISTING ITEMS</option>
                </select>
              </div>

              {/* Watchlist Name or Selection */}
              {importMode === 'create' ? (
                <div>
                  <label className="block text-[11px] text-zinc-400 uppercase mb-1">
                    Watchlist Base Name (Max 32)
                  </label>
                  <input
                    type="text"
                    value={baseName}
                    onChange={(e) => setBaseName(e.target.value)}
                    maxLength={32}
                    className="w-full bg-[#18181f] border border-[#27272a] text-white text-xs px-2.5 py-1.5 rounded outline-none focus:border-terminal-amber font-mono"
                    placeholder="Watchlist Name"
                  />
                  {!isBaseNameValid && (
                    <span className="text-[10px] text-terminal-red">
                      Only letters, numbers, spaces, - and _ allowed
                    </span>
                  )}
                </div>
              ) : (
                <div>
                  <label className="block text-[11px] text-zinc-400 uppercase mb-1">
                    Target Watchlist {importMode === 'append' && `(${targetCurrentCount}/1000)`}
                  </label>
                  <select
                    value={targetId}
                    onChange={(e) => setTargetId(Number(e.target.value))}
                    className="w-full bg-[#18181f] border border-[#27272a] text-white text-xs px-2.5 py-1.5 rounded outline-none focus:border-terminal-amber"
                  >
                    {watchlists.map((wl) => (
                      <option key={wl.id} value={wl.id}>
                        {wl.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Split Sections Toggle (Create Mode only) */}
              <div className="flex flex-col justify-end">
                <label
                  className={`flex items-center gap-2 p-2 rounded border transition-colors cursor-pointer ${
                    importMode === 'create'
                      ? 'bg-[#18181f] border-[#27272a] text-zinc-200'
                      : 'opacity-40 border-transparent text-zinc-500 cursor-not-allowed'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={splitSections && importMode === 'create'}
                    onChange={(e) => setSplitSections(e.target.checked)}
                    disabled={importMode !== 'create'}
                    className="accent-terminal-amber cursor-pointer"
                  />
                  <div className="text-[11px] leading-tight">
                    <span className="font-bold">SPLIT SECTIONS</span>
                    <p className="text-[10px] text-zinc-400">Create a separate list per section header</p>
                  </div>
                </label>
              </div>
            </div>
          </div>

          {/* KPI Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="p-3 bg-[#121216] border border-[#27272a] rounded">
              <div className="text-[10px] text-zinc-400 uppercase font-mono">Ready to Import</div>
              <div className="text-lg font-bold font-mono text-terminal-amber tabular-nums">
                {resolution.summary.readyToImport}
              </div>
            </div>

            <div className="p-3 bg-[#121216] border border-[#27272a] rounded">
              <div className="text-[10px] text-zinc-400 uppercase font-mono">Duplicates Skipped</div>
              <div className="text-lg font-bold font-mono text-zinc-300 tabular-nums">
                {resolution.summary.duplicates}
              </div>
            </div>

            <div className="p-3 bg-[#121216] border border-[#27272a] rounded">
              <div className="text-[10px] text-zinc-400 uppercase font-mono">Unsupported (Non-NSE)</div>
              <div className="text-lg font-bold font-mono text-rose-400 tabular-nums">
                {resolution.summary.unsupported}
              </div>
            </div>

            <div className="p-3 bg-[#121216] border border-[#27272a] rounded">
              <div className="text-[10px] text-zinc-400 uppercase font-mono">
                {splitSections && importMode === 'create' ? 'Valid Sections' : 'Sections'}
              </div>
              <div className="text-lg font-bold font-mono text-emerald-400 tabular-nums">
                {splitSections && importMode === 'create'
                  ? `${resolution.summary.validSectionsCount} of ${parseResult.sections.length}`
                  : parseResult.summary.sectionsCount}
              </div>
            </div>
          </div>

          {/* Append mode target duplicate notice */}
          {importMode === 'append' && resolution.summary.alreadyInTarget > 0 && (
            <div className="p-2.5 bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs rounded flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>
                {resolution.summary.alreadyInTarget} symbol
                {resolution.summary.alreadyInTarget === 1 ? '' : 's'} already exist in &quot;
                {watchlists.find((w) => w.id === targetId)?.name}&quot; and will be skipped.
              </span>
            </div>
          )}

          {/* Capacity overflow notice */}
          {resolution.summary.capacityExceeded > 0 && (
            <div className="p-2.5 bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>
                {resolution.summary.capacityExceeded} symbol
                {resolution.summary.capacityExceeded === 1 ? '' : 's'} exceed the 1,000 symbol limit and
                will be skipped.
              </span>
            </div>
          )}

          {/* Preview Table */}
          {resolution.items.length > 0 && (
            <div className="border border-[#27272a] rounded-lg bg-[#121216] overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-[#27272a] bg-[#18181f]">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-zinc-300 uppercase font-mono">Preview Symbols</span>
                  <span className="text-[11px] text-zinc-500">({resolution.items.length} total)</span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5 bg-[#121216] px-2 py-1 rounded border border-[#27272a]">
                    <Filter className="w-3 h-3 text-zinc-400" />
                    <input
                      type="text"
                      placeholder="Filter preview..."
                      value={filterText}
                      onChange={(e) => setFilterText(e.target.value)}
                      className="bg-transparent text-[11px] text-white outline-none w-28 font-mono"
                    />
                  </div>
                  <div className="flex gap-1 text-[10px]">
                    <button
                      onClick={selectAllValid}
                      className="text-terminal-amber hover:underline px-1.5 py-0.5 cursor-pointer"
                    >
                      SELECT ALL
                    </button>
                    <span className="text-zinc-600">|</span>
                    <button onClick={deselectAll} className="text-zinc-400 hover:underline px-1.5 py-0.5 cursor-pointer">
                      DESELECT ALL
                    </button>
                  </div>
                </div>
              </div>

              <div className="max-h-60 overflow-y-auto font-mono text-xs">
                <table className="w-full text-left border-collapse">
                  <thead className="bg-[#0f0f13] text-[10px] text-zinc-400 uppercase sticky top-0 border-b border-[#27272a]">
                    <tr>
                      <th className="py-2 px-3 w-10 text-center">Inc</th>
                      <th className="py-2 px-3">Symbol</th>
                      <th className="py-2 px-3">Exchange</th>
                      <th className="py-2 px-3">Section</th>
                      <th className="py-2 px-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1e1e24]">
                    {filteredPreviewItems.map((item) => {
                      return (
                        <tr
                          key={item.id}
                          className={`hover:bg-[#181820] transition-colors ${
                            item.status === 'unsupported'
                              ? 'opacity-60 bg-rose-950/10'
                              : item.status === 'duplicate' || item.status === 'already_present'
                              ? 'opacity-70 bg-amber-950/10'
                              : item.status === 'capacity_exceeded'
                              ? 'opacity-60 bg-rose-950/10'
                              : ''
                          }`}
                        >
                          <td className="py-1.5 px-3 text-center">
                            <input
                              type="checkbox"
                              checked={item.selected}
                              onChange={() => toggleItemSelection(item.id)}
                              disabled={!item.isValidNse}
                              className="accent-terminal-amber cursor-pointer"
                            />
                          </td>
                          <td className="py-1.5 px-3 font-bold font-mono text-white">{item.symbol}</td>
                          <td className="py-1.5 px-3">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                item.exchange === 'NSE'
                                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                  : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                              }`}
                            >
                              {item.exchange}
                            </span>
                          </td>
                          <td className="py-1.5 px-3 text-zinc-400 text-[11px] truncate max-w-[120px]">
                            {item.section}
                          </td>
                          <td className="py-1.5 px-3">
                            {item.status === 'valid' && (
                              <span className="text-emerald-400 font-bold flex items-center gap-1">
                                <Check className="w-3 h-3" /> READY
                              </span>
                            )}
                            {item.status === 'duplicate' && (
                              <span className="text-terminal-amber font-bold">DUPLICATE (SKIPPED)</span>
                            )}
                            {item.status === 'already_present' && (
                              <span className="text-amber-400 font-bold">IN TARGET (SKIPPED)</span>
                            )}
                            {item.status === 'capacity_exceeded' && (
                              <span className="text-rose-400 font-bold">CAPACITY EXCEEDED</span>
                            )}
                            {item.status === 'unsupported' && (
                              <span className="text-rose-400 text-[11px]">{item.reason || 'UNSUPPORTED'}</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Import error banner */}
          {importError && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/40 text-terminal-red rounded flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{importError}</span>
            </div>
          )}
        </div>

        {/* Bento Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-[#27272a] bg-[#09090b]">
          <div className="text-zinc-400 text-xs">
            {resolution.submitDisabledReason ? (
              <span className="text-terminal-amber font-mono font-bold">
                ⚠️ {resolution.submitDisabledReason}
              </span>
            ) : !isBaseNameValid ? (
              <span className="text-terminal-red font-mono font-bold">
                ⚠️ Invalid watchlist name
              </span>
            ) : resolution.summary.readyToImport > 0 ? (
              <span className="text-zinc-300">
                Ready to import <strong className="text-white font-mono">{resolution.summary.readyToImport}</strong> symbols.
              </span>
            ) : (
              <span className="text-zinc-500">No valid symbols selected.</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={importMutation.isPending}
              className="px-3 py-1.5 text-zinc-300 hover:text-white border border-[#27272a] hover:bg-[#18181f] rounded text-xs font-bold transition-colors cursor-pointer"
            >
              CANCEL
            </button>
            <button
              type="button"
              onClick={() => importMutation.mutate()}
              disabled={!canSubmit}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-terminal-amber hover:bg-amber-400 text-black font-bold rounded text-xs disabled:opacity-40 transition-colors cursor-pointer"
            >
              {importMutation.isPending ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  IMPORTING...
                </>
              ) : (
                <>
                  <Check className="w-3.5 h-3.5" />
                  IMPORT ({resolution.summary.readyToImport})
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
