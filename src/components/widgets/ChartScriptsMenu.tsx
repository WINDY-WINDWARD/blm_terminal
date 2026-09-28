'use client';
/**
 * BLM Script Lab v1 — Scripts popover for the chart toolbar.
 * Single Fx-style checkbox list (checked = on this chart): checkbox toggles
 * attach/detach, ⚙ opens the params modal (live-apply), ✎ refines with AI.
 * Mutations go through POST /chart-state (per-slot upsert; detach =
 * enabled:false) and invalidate the slots query.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtomValue, useSetAtom } from 'jotai';
import { cn } from '@/lib/utils';
import {
  activePanelsAtom,
  aiPrefillAtom,
  focusedPanelAtom,
  AI_REFINE_REQUEST_KEY,
} from '@/store/terminalStore';
import { buildRefinePrompt, findAiPanel } from '@/lib/scripts/handoff';
import type {
  SavedScriptDetail,
  SavedScriptSummary,
  ScriptChartSlot,
  ScriptParam,
} from '@/lib/scripts/types';
import {
  deleteScript,
  fetchScripts,
  setChartSlot,
  type ChartSlotSet,
} from '@/lib/scripts/api';
import { pruneStashedScript } from '@/lib/scripts/cardStash';
import { ScriptParamForm } from '@/lib/scripts/paramForm';
import { computePopoverPos } from '@/lib/scripts/popoverPos';

interface ChartScriptsMenuProps {
  panelId: string;
  slots: ScriptChartSlot[];
  details: Map<number, SavedScriptDetail>;
  refetchSlots: () => void;
  lastError: string | null;
}

interface Row {
  id: number;
  name: string;
  description?: string | null;
  isBuiltin: boolean;
  enabled: boolean;
  revNo: number | null;
  params: ScriptParam[];
  slot: ScriptChartSlot | undefined;
}

export function ChartScriptsMenu({
  panelId,
  slots,
  details,
  refetchSlots,
  lastError,
}: ChartScriptsMenuProps) {
  const [open, setOpen] = useState(false);
  const [paramScriptId, setParamScriptId] = useState<number | null>(null);
  // Popover anchoring: the popover is portaled to document.body with
  // `position: fixed` so it escapes the chart Panel's `overflow-hidden`
  // clipping. Position is derived from the button rect on open.
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [popPos, setPopPos] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    setPopPos(
      computePopoverPos(rect, { width: window.innerWidth, height: window.innerHeight }),
    );
  }, [open]);

  // Dismiss the portaled popover: outside click (button excluded — it
  // toggles), Esc, scroll, resize.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (!t) return;
      if (popoverRef.current?.contains(t)) return;
      if (buttonRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onScrollResize = () => setOpen(false);
    document.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScrollResize, true);
    window.addEventListener('resize', onScrollResize);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScrollResize, true);
      window.removeEventListener('resize', onScrollResize);
    };
  }, [open]);
  const queryClient = useQueryClient();
  const panels = useAtomValue(activePanelsAtom);
  const setFocusedPanel = useSetAtom(focusedPanelAtom);
  const setPrefill = useSetAtom(aiPrefillAtom);

  /**
   * AI handoff delivery (focus-or-popout). Prefills the AI input (which
   * switches it to Script mode): same-window AI panel → atom + focus;
   * no AI panel on the grid → localStorage bridge + AI popout.
   */
  const deliverToAi = (prompt: string) => {
    const aiPanelId = findAiPanel(panels);
    if (aiPanelId) {
      setPrefill({ text: prompt, ts: Date.now() });
      setFocusedPanel(aiPanelId);
    } else {
      try {
        window.localStorage.setItem(
          AI_REFINE_REQUEST_KEY,
          JSON.stringify({ text: prompt, ts: Date.now() }),
        );
      } catch {
        /* private-mode quota — popout still opens, prompt is lost */
      }
      window.open('/widget/AI', '_blank', 'width=1000,height=700');
    }
    setOpen(false);
  };

  /**
   * Refine-with-AI handoff: prefill with a script-scoped prompt.
   */
  const refineWithAi = (scriptId: number, name: string, revNo: number | null) => {
    deliverToAi(buildRefinePrompt(name, scriptId, revNo));
  };

  /**
   * New-script-via-AI handoff: the AI asks what to build, writes it,
   * validates it, and returns an Accept card that attaches here.
   */
  const createWithAi = () => {
    deliverToAi(
      'Create a new chart script for me. Ask what it should compute and show, then write it.',
    );
  };

  const catalogQuery = useQuery({
    queryKey: ['scripts-catalog'],
    queryFn: fetchScripts,
    enabled: open,
    staleTime: 60_000,
    retry: 1,
  });

  const mutate = useMutation({
    mutationFn: (slot: ChartSlotSet) => setChartSlot(panelId, slot),
    onSuccess: (_data, slot) => {
      void queryClient.invalidateQueries({ queryKey: ['script-slots', panelId] });
      void queryClient.invalidateQueries({ queryKey: ['script-detail', slot.script_id] });
      void queryClient.invalidateQueries({ queryKey: ['scripts-catalog'] });
      refetchSlots();
    },
  });

  const delMutate = useMutation({
    mutationFn: (scriptId: number) => deleteScript(scriptId),
    onSuccess: (_data, scriptId) => {
      pruneStashedScript(scriptId);
      void queryClient.invalidateQueries({ queryKey: ['script-slots', panelId] });
      void queryClient.invalidateQueries({ queryKey: ['script-detail', scriptId] });
      void queryClient.invalidateQueries({ queryKey: ['scripts-catalog'] });
      refetchSlots();
      setParamScriptId(null);
    },
    onError: (err: unknown) => {
      alert(err instanceof Error ? err.message : 'Delete failed');
    },
  });

  const busy = mutate.isPending || delMutate.isPending;

  const handleDelete = (row: Row) => {
    if (row.isBuiltin) return;
    if (!confirm(`Delete script "${row.name}"? It will be lost forever.`)) return;
    delMutate.mutate(row.id);
  };
  const enabledIds = new Set(slots.filter((s) => s.enabled).map((s) => s.script_id));
  const slotById = new Map(slots.map((s) => [s.script_id, s]));
  const catalog: SavedScriptSummary[] = catalogQuery.data ?? [];

  // Merged rows: every known script exactly once. Enabled-but-absent-from-
  // catalog slots (stale cache) render as a fallback row so they stay
  // detachable.
  const rows: Row[] = [
    ...catalog.map((c) => {
      const slot = slotById.get(c.id);
      const detail = details.get(c.id);
      return {
        id: c.id,
        name: c.name,
        description: c.description,
        isBuiltin: c.is_builtin,
        enabled: enabledIds.has(c.id),
        revNo: detail?.head_rev_no ?? null,
        params: detail?.head?.manifest?.params ?? [],
        slot,
      };
    }),
    ...slots
      .filter((s) => !catalog.some((c) => c.id === s.script_id))
      .map((s) => {
        const detail = details.get(s.script_id);
        return {
          id: s.script_id,
          name: detail?.name ?? `#${s.script_id}`,
          description: null,
          isBuiltin: false,
          enabled: s.enabled,
          revNo: detail?.head_rev_no ?? null,
          params: detail?.head?.manifest?.params ?? [],
          slot: s,
        };
      }),
  ];

  const toggle = (row: Row) => {
    mutate.mutate({
      script_id: row.id,
      enabled: !row.enabled,
      // Omit on fresh enable so the backend keeps any stored params;
      // explicit dict only when re-sending known values.
      ...(row.slot ? { param_values: row.slot.param_values } : {}),
    });
  };

  const setParams = (row: Row, values: Record<string, number | boolean | string>) => {
    mutate.mutate({ script_id: row.id, enabled: true, param_values: values });
  };

  // Esc closes the params modal.
  useEffect(() => {
    if (paramScriptId === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setParamScriptId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [paramScriptId]);

  const paramRow = paramScriptId !== null ? rows.find((r) => r.id === paramScriptId) : undefined;
  const enabledCount = enabledIds.size;

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'px-1.5 py-0.5 text-[10px] font-mono border transition-colors',
          open || enabledCount > 0
            ? 'border-terminal-amber text-terminal-amber bg-black'
            : 'border-terminal-gray text-white/70 hover:text-terminal-amber hover:border-terminal-amber bg-black',
        )}
        title="Chart scripts (Script Lab v1) — check to show, uncheck to hide"
      >
        Σ{enabledCount > 0 ? ` ${enabledCount}` : ''}
      </button>

      {open &&
        popPos &&
        createPortal(
          <div
            ref={popoverRef}
            className="fixed z-[90] w-72 max-h-96 overflow-y-auto bg-black border border-terminal-gray shadow-lg text-xs font-mono"
            style={{ top: popPos.top, left: popPos.left }}
          >
          {lastError && (
            <div className="px-2 py-1 text-terminal-red border-b border-terminal-gray/40 text-[10px]">
              {lastError}
            </div>
          )}

          <div className="px-2 py-1 text-white/40 text-[10px] tracking-wider">
            SCRIPTS — CHECK TO SHOW
          </div>
          {catalogQuery.isPending && (
            <div className="px-2 py-1 text-white/40 text-[11px]">Loading…</div>
          )}
          {catalogQuery.isError && (
            <div className="px-2 py-1 text-terminal-red text-[11px]">Catalog unavailable</div>
          )}
          {catalogQuery.data && rows.length === 0 && (
            <div className="px-2 py-1 text-white/40 text-[11px]">No scripts yet — create one via AI below.</div>
          )}
          {rows.map((row) => (
            <div key={row.id} className="border-b border-terminal-gray/40 last:border-b-0">
              <div
                className="w-full text-left px-2 py-1 flex items-center gap-2 text-white/80"
                title={row.description ?? row.name}
              >
                <input
                  type="checkbox"
                  checked={row.enabled}
                  disabled={busy}
                  onChange={() => toggle(row)}
                  className="accent-[#FFB900] w-3 h-3 flex-shrink-0 cursor-pointer disabled:cursor-not-allowed"
                  title={row.enabled ? `Hide ${row.name}` : `Show ${row.name}`}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => toggle(row)}
                  className="truncate flex-1 text-left cursor-pointer hover:text-terminal-amber disabled:cursor-not-allowed"
                >
                  {row.name}
                </button>
                {row.isBuiltin && <span className="text-white/30 text-[10px]">builtin</span>}
                {row.revNo !== null && (
                  <span
                    className="text-white/30 text-[10px]"
                    title={`Head revision ${row.revNo} — each AI edit saves a new revision`}
                  >
                    rev {row.revNo}
                  </span>
                )}
                {row.params.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setParamScriptId(row.id)}
                    className="text-white/50 hover:text-terminal-amber px-0.5"
                    title="Parameters"
                  >
                    ⚙
                  </button>
                )}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => refineWithAi(row.id, row.name, row.revNo)}
                  className="text-white/50 hover:text-terminal-amber text-[10px] disabled:opacity-40"
                  title="Refine this script with AI (prefills the AI input)"
                >
                  ✎
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={createWithAi}
            className="w-full text-left px-2 py-1.5 flex items-center gap-2 text-terminal-amber hover:bg-zinc-800 border-t border-terminal-gray/60"
            title="Describe a new script to the AI — it writes, validates and saves it, then you Accept it onto this chart"
          >
            <span>＋</span>
            <span>New script via AI…</span>
          </button>
          </div>,
          document.body,
        )}

      {paramRow && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
          onClick={() => setParamScriptId(null)}
        >
          <div
            className="w-80 max-h-[80vh] overflow-y-auto bg-black border border-terminal-amber shadow-lg text-xs font-mono"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 px-3 py-2 border-b border-terminal-gray/60">
              <span className="text-terminal-amber truncate flex-1" title={paramRow.name}>
                {paramRow.name}
              </span>
              {paramRow.revNo !== null && (
                <span
                  className="text-white/30 text-[10px]"
                  title={`Head revision ${paramRow.revNo} — each AI edit saves a new revision`}
                >
                  rev {paramRow.revNo}
                </span>
              )}
              <button
                type="button"
                onClick={() => setParamScriptId(null)}
                className="text-white/50 hover:text-terminal-red"
                title="Close (Esc)"
              >
                ✕
              </button>
            </div>
            <div className="px-3 py-2">
              <ScriptParamForm
                params={paramRow.params}
                values={paramRow.slot?.param_values ?? {}}
                onChange={(values) => setParams(paramRow, values)}
              />
            </div>
            {!paramRow.isBuiltin && (
              <div className="px-3 py-2 border-t border-terminal-gray/60 flex justify-end">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleDelete(paramRow)}
                  className="text-[11px] text-terminal-red/80 hover:text-terminal-red border border-terminal-red/30 hover:border-terminal-red/60 rounded px-2 py-1 transition-colors disabled:opacity-50"
                  title="Delete this script permanently"
                >
                  {delMutate.isPending ? 'Deleting…' : 'Delete script'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
