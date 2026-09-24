'use client';
/**
 * BLM Script Lab v1 — Scripts popover for the chart toolbar.
 * "On this chart" (enabled slots + param forms + remove) and "Browse"
 * (all saved scripts + enable). Mutations go through POST /chart-state
 * (per-slot upsert; detach = enabled:false) and invalidate the slots query.
 */
import { useState } from 'react';
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
} from '@/lib/scripts/types';
import {
  fetchScripts,
  setChartSlot,
  type ChartSlotSet,
} from '@/lib/scripts/api';
import { ScriptParamForm } from '@/lib/scripts/paramForm';

interface ChartScriptsMenuProps {
  panelId: string;
  slots: ScriptChartSlot[];
  details: Map<number, SavedScriptDetail>;
  refetchSlots: () => void;
  lastError: string | null;
}

export function ChartScriptsMenu({
  panelId,
  slots,
  details,
  refetchSlots,
  lastError,
}: ChartScriptsMenuProps) {
  const [open, setOpen] = useState(false);
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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['script-slots', panelId] });
      refetchSlots();
    },
  });

  const enabled = slots.filter((s) => s.enabled);
  const enabledIds = new Set(enabled.map((s) => s.script_id));
  const catalog: SavedScriptSummary[] = catalogQuery.data ?? [];
  const available = catalog.filter((c) => !enabledIds.has(c.id));
  const busy = mutate.isPending;

  const setParams = (slot: ScriptChartSlot, values: Record<string, number | boolean | string>) => {
    mutate.mutate({ script_id: slot.script_id, enabled: true, param_values: values });
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'px-1.5 py-0.5 text-[10px] font-mono border transition-colors',
          open || enabled.length > 0
            ? 'border-terminal-amber text-terminal-amber bg-black'
            : 'border-terminal-gray text-white/70 hover:text-terminal-amber hover:border-terminal-amber bg-black',
        )}
        title="Chart scripts (Script Lab v1) — enable saved scripts on this chart"
      >
        Σ{enabled.length > 0 ? ` ${enabled.length}` : ''}
      </button>

      {open && (
        <div className="absolute z-50 left-0 top-full mt-0.5 w-72 max-h-96 overflow-y-auto bg-black border border-terminal-gray shadow-lg text-xs font-mono">
          {lastError && (
            <div className="px-2 py-1 text-terminal-red border-b border-terminal-gray/40 text-[10px]">
              {lastError}
            </div>
          )}

          <div className="px-2 py-1 text-white/40 text-[10px] tracking-wider">
            ON THIS CHART
          </div>
          {enabled.length === 0 && (
            <div className="px-2 py-1 text-white/40 text-[11px]">No scripts enabled.</div>
          )}
          {enabled.map((slot) => {
            const detail = details.get(slot.script_id);
            const manifest = detail?.head?.manifest;
            return (
              <div key={slot.script_id} className="border-b border-terminal-gray/40 last:border-b-0 px-2 py-1">
                <div className="flex items-center gap-2">
                  <span className="text-terminal-amber truncate flex-1" title={detail?.name ?? `#${slot.script_id}`}>
                    {detail?.name ?? `#${slot.script_id}`}
                  </span>
                  <span className="text-white/30 text-[10px]">r{detail?.head_rev_no ?? '?'}</span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      refineWithAi(slot.script_id, detail?.name ?? `#${slot.script_id}`, detail?.head_rev_no ?? null)
                    }
                    className="text-white/50 hover:text-terminal-amber text-[10px] disabled:opacity-40"
                    title="Refine this script with AI (prefills the AI input)"
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      mutate.mutate({
                        script_id: slot.script_id,
                        enabled: false,
                        param_values: slot.param_values ?? {},
                      })
                    }
                    className="text-white/50 hover:text-terminal-red text-[10px] disabled:opacity-40"
                    title="Remove script from this chart"
                  >
                    ✕
                  </button>
                </div>
                {manifest && (manifest.params ?? []).length > 0 && (
                  <ScriptParamForm
                    params={manifest.params ?? []}
                    values={slot.param_values ?? {}}
                    onChange={(values) => setParams(slot, values)}
                  />
                )}
              </div>
            );
          })}

          <div className="px-2 py-1 text-white/40 text-[10px] tracking-wider border-t border-terminal-gray/60">
            BROWSE
          </div>
          {catalogQuery.isPending && (
            <div className="px-2 py-1 text-white/40 text-[11px]">Loading…</div>
          )}
          {catalogQuery.isError && (
            <div className="px-2 py-1 text-terminal-red text-[11px]">Catalog unavailable</div>
          )}
          {catalogQuery.data && available.length === 0 && (
            <div className="px-2 py-1 text-white/40 text-[11px]">All scripts enabled.</div>
          )}
          {available.map((c) => (
            <button
              key={c.id}
              type="button"
              disabled={busy}
              onClick={() =>
                mutate.mutate({ script_id: c.id, enabled: true, param_values: {} })
              }
              className="w-full text-left px-2 py-1 flex items-center gap-2 text-white/80 hover:bg-zinc-800 disabled:opacity-40"
              title={c.description ?? c.name}
            >
              <span className="text-terminal-amber">+</span>
              <span className="truncate flex-1">{c.name}</span>
              {c.is_builtin && <span className="text-white/30 text-[10px]">builtin</span>}
            </button>
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
        </div>
      )}
    </div>
  );
}
