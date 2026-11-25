'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import {
  useDeleteWorkflow,
  useMarkAllRunsRead,
  useMarkRunRead,
  useRunWorkflowNow,
  useToggleWorkflow,
  useWorkflowRuns,
} from '@/hooks/useAiWorkflows';
import type { Workflow, WorkflowRun } from '@/types/aiWorkflowTypes';
import { formatIst } from '@/lib/aiWorkflowTime';

export interface AiWorkflowDrawerProps {
  open: boolean;
  onClose: () => void;
  workflows: Workflow[];
  runs?: WorkflowRun[];
  unreadRuns?: number;
  loading: boolean;
  runsLoading: boolean;
  onOpenRun: (run: WorkflowRun) => void;
  onCreateWorkflow: () => void;
  onEditWorkflow: (workflow: Workflow) => void;
}

type TabType = 'scheduled' | 'inbox';

// Why a slot did not produce a run. The backend records one of these on
// every skipped run, and an unexplained skip reads like a silent failure.
const SKIP_REASON_LABELS: Record<string, string> = {
  still_running: 'the previous run was still running',
  missed_window: 'outside the catch-up window',
  never_started: 'it never started',
};

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        'px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 flex items-center gap-1 active:scale-[0.96]',
        active
          ? 'text-terminal-amber font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent',
      )}
    >
      {label}
    </button>
  );
}

function getRunAccentClass(status: string, trigger: string): string {
  if (status === 'failed') return 'border-l-red-500';
  if (trigger === 'schedule') return 'border-l-terminal-amber';
  if (trigger === 'catch_up') return 'border-l-blue-400';
  return 'border-l-zinc-500';
}

export function AiWorkflowDrawer({
  open,
  onClose,
  workflows,
  runs = [],
  unreadRuns,
  loading,
  runsLoading,
  onOpenRun,
  onCreateWorkflow,
  onEditWorkflow,
}: AiWorkflowDrawerProps) {
  const [tab, setTab] = useState<TabType>('scheduled');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const [runsLimit, setRunsLimit] = useState(20);
  const { data: pagedRunsData, isLoading: pagedRunsLoading } = useWorkflowRuns({
    limit: runsLimit,
    enabled: open,
  });

  const runWorkflowNow = useRunWorkflowNow();
  const toggleWorkflow = useToggleWorkflow();
  const deleteWorkflow = useDeleteWorkflow();
  const markRunRead = useMarkRunRead();
  const markAllRunsRead = useMarkAllRunsRead();

  if (!open) return null;

  const displayRuns = pagedRunsData?.items ?? runs;
  const isRunsLoading = runsLoading || pagedRunsLoading;
  const unreadRunsCount = unreadRuns ?? displayRuns.filter((r) => !r.is_read).length;
  const hasMoreRuns = pagedRunsData ? pagedRunsData.has_more : runs.length >= runsLimit;

  return (
    <aside className="w-72 shrink-0 bg-[#0c0c0f] border-l border-[#27272a] flex flex-col z-20 select-none">
      {/* Header Row */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#27272a] shrink-0">
        <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-zinc-400">
          WORKFLOWS
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCreateWorkflow}
            className="text-zinc-400 hover:text-white text-xs px-1"
            title="New workflow"
            aria-label="New workflow"
          >
            +
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-zinc-400 hover:text-white text-xs px-1"
            title="Close drawer"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center border-b border-[#27272a] bg-[#09090b] px-2 shrink-0">
        <TabButton
          active={tab === 'scheduled'}
          onClick={() => setTab('scheduled')}
          label={`SCHEDULED (${workflows.length})`}
        />
        <TabButton
          active={tab === 'inbox'}
          onClick={() => setTab('inbox')}
          label={`INBOX (${unreadRunsCount})`}
        />
      </div>

      {/* Body */}
      <div className="overflow-y-auto custom-scroll flex-1 p-2 select-text">
        {tab === 'scheduled' ? (
          /* SCHEDULED TAB */
          <div className="flex flex-col gap-1.5">
            {toggleWorkflow.isError && (
              <div className="px-1 py-1 text-[10px] font-mono text-red-400 border border-red-900/60 rounded bg-red-950/30">
                {toggleWorkflow.error instanceof Error
                  ? toggleWorkflow.error.message
                  : 'Failed to change the workflow state.'}
              </div>
            )}
            {loading && workflows.length === 0 ? (
              <div className="p-4 text-center text-zinc-500 font-mono text-xs">
                Loading workflows…
              </div>
            ) : workflows.length === 0 ? (
              <div className="p-4 text-center font-mono">
                <div className="text-zinc-400 text-xs">No workflows yet.</div>
                <div className="text-[10px] text-zinc-500 mt-2 leading-relaxed">
                  Ask the copilot: &quot;brief me on my watchlist every weekday at 10&quot;
                </div>
              </div>
            ) : (
              workflows.map((wf) => {
                const isExpanded = expandedId === wf.id;
                const lastRun = displayRuns.find((r) => r.workflow_id === wf.id);
                const lastFailed = lastRun?.status === 'failed';
                const isToggling =
                  toggleWorkflow.isPending && toggleWorkflow.variables?.id === wf.id;
                // Reflect a just-finished toggle immediately, before the list refetches.
                const isEnabled =
                  toggleWorkflow.data?.id === wf.id
                    ? toggleWorkflow.data.is_enabled
                    : wf.is_enabled;

                const dotColor = lastFailed
                  ? 'bg-red-500'
                  : isEnabled
                    ? 'bg-emerald-400'
                    : 'bg-zinc-500';

                const wfRecentRuns = displayRuns
                  .filter((r) => r.workflow_id === wf.id)
                  .slice(0, 3);

                return (
                  <div
                    key={wf.id}
                    onClick={() => setExpandedId(isExpanded ? null : wf.id)}
                    className="group p-2 rounded bg-[#121216] border border-[#27272a] hover:border-terminal-amber/40 cursor-pointer transition-colors"
                  >
                    {/* Line 1 */}
                    <div className="flex items-center gap-1.5">
                      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dotColor)} />
                      <span
                        className={cn(
                          'text-xs font-mono truncate flex-1 font-medium',
                          isEnabled ? 'text-zinc-200' : 'text-zinc-500',
                        )}
                        title={wf.name}
                      >
                        {wf.name}
                      </span>
                      {!isEnabled && (
                        <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400">
                          Paused
                        </span>
                      )}
                      {/* Hover actions */}
                      <div className="opacity-60 group-hover:opacity-100 flex items-center gap-0.5 transition-opacity shrink-0">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            runWorkflowNow.mutate(wf.id);
                          }}
                          title="Run now"
                          className="w-5 h-5 flex items-center justify-center rounded hover:bg-zinc-800 text-zinc-400 hover:text-terminal-amber text-[10px]"
                        >
                          ▶
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleWorkflow.mutate({
                              id: wf.id,
                              is_enabled: !isEnabled,
                            });
                          }}
                          disabled={isToggling}
                          aria-pressed={!isEnabled}
                          title={isEnabled ? 'Pause scheduled runs' : 'Resume scheduled runs'}
                          className={cn(
                            'w-5 h-5 flex items-center justify-center rounded hover:bg-zinc-800 text-[10px] transition-colors',
                            isEnabled
                              ? 'text-zinc-400 hover:text-terminal-amber'
                              : 'text-terminal-amber',
                            isToggling && 'opacity-50 animate-pulse',
                          )}
                        >
                          {isToggling ? '···' : isEnabled ? '⏸' : '▶'}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onEditWorkflow(wf);
                          }}
                          title="Edit"
                          className="w-5 h-5 flex items-center justify-center rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 text-[10px]"
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteWorkflow.mutate(wf.id);
                          }}
                          title="Delete"
                          className="w-5 h-5 flex items-center justify-center rounded hover:bg-zinc-800 text-zinc-400 hover:text-red-400 text-[10px]"
                        >
                          ✕
                        </button>
                      </div>
                    </div>

                    {/* Line 2 */}
                    <div className="text-[10px] font-mono text-zinc-500 truncate mt-0.5 pl-3">
                      {wf.schedule_label}
                      {wf.catch_up_enabled && ` · catch-up ${wf.catch_up_window_hours}h`}
                      {!isEnabled && (
                        <span className="text-terminal-amber"> · paused, will not run</span>
                      )}
                    </div>

                    {/* Expanded details */}
                    {isExpanded && (
                      <div className="mt-2 pt-2 border-t border-[#27272a]/60 flex flex-col gap-1.5 pl-3">
                        <div className="text-[11px] font-mono text-zinc-400 line-clamp-3">
                          {wf.prompt}
                        </div>
                        {wf.allow_write_tools && (
                          <div>
                            <span className="inline-block text-[9px] font-mono px-1.5 py-0.5 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
                              Allow actions
                            </span>
                          </div>
                        )}
                        {wfRecentRuns.length > 0 && (
                          <div className="space-y-1 mt-1 pt-1.5 border-t border-[#27272a]/40">
                            <div className="text-[9px] font-mono uppercase tracking-wider text-zinc-500">
                              Recent runs
                            </div>
                            {wfRecentRuns.map((r) => (
                              <div
                                key={r.id}
                                className="flex items-center justify-between text-[10px] font-mono text-zinc-400"
                              >
                                <span
                                  className={cn(
                                    'capitalize',
                                    r.status === 'succeeded'
                                      ? 'text-emerald-400'
                                      : r.status === 'failed'
                                        ? 'text-red-400'
                                        : 'text-zinc-400',
                                  )}
                                >
                                  {r.status}
                                </span>
                                <span>{formatIst(r.scheduled_for)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        ) : (
          /* INBOX TAB */
          <div className="flex flex-col gap-2">
            {unreadRunsCount > 0 && (
              <div className="flex items-center justify-end px-1 pb-1">
                <button
                  type="button"
                  onClick={() => markAllRunsRead.mutate()}
                  className="text-[10px] font-mono text-terminal-amber hover:text-white font-medium"
                >
                  MARK ALL READ
                </button>
              </div>
            )}

            {isRunsLoading && displayRuns.length === 0 ? (
              <div className="p-4 text-center text-zinc-500 font-mono text-xs">
                Loading runs…
              </div>
            ) : displayRuns.length === 0 ? (
              <div className="p-4 text-center text-zinc-500 font-mono text-xs">
                No runs yet.
              </div>
            ) : (
              displayRuns.map((run) => {
                const wf = workflows.find((w) => w.id === run.workflow_id);
                const title = run.name_snapshot || wf?.name || 'Workflow';

                return (
                  <div
                    key={run.id}
                    className={cn(
                      'p-2.5 bg-[#121216] border border-[#27272a] border-l-2 rounded-r flex flex-col gap-1',
                      getRunAccentClass(run.status, run.trigger),
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className="text-xs font-mono font-medium text-zinc-200 truncate flex-1"
                        title={title}
                      >
                        {title}
                      </span>
                      {!run.is_read && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-terminal-amber shrink-0"
                          title="Unread"
                        />
                      )}
                    </div>

                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-zinc-500">
                      <span>{formatIst(run.scheduled_for)}</span>
                      <span className="text-[9px] uppercase font-mono px-1 py-0.2 rounded bg-zinc-800 text-zinc-400">
                        {run.trigger}
                      </span>
                    </div>

                    {run.output_summary && (
                      <div className="text-xs font-mono text-zinc-300 line-clamp-2 mt-0.5 leading-relaxed">
                        {run.output_summary}
                      </div>
                    )}

                    {run.status === 'skipped' && (
                      <div className="mt-0.5 text-[10px] font-mono text-zinc-500">
                        <span className="text-[9px] uppercase px-1 py-0.2 rounded bg-zinc-800 text-zinc-400">
                          SKIPPED
                        </span>{' '}
                        {SKIP_REASON_LABELS[run.skip_reason ?? ''] ?? 'no reason recorded'}
                      </div>
                    )}

                    <div className="flex items-center justify-end pt-1">
                      {run.session_id ? (
                        <button
                          type="button"
                          onClick={() => {
                            if (!run.is_read) {
                              markRunRead.mutate(run.id);
                            }
                            onOpenRun(run);
                          }}
                          className="text-[10px] font-mono px-2 py-0.5 border border-[#27272a] hover:border-terminal-amber hover:text-terminal-amber rounded text-zinc-300 transition-colors"
                        >
                          OPEN
                        </button>
                      ) : (
                        <span
                          title="This run has not produced a transcript yet."
                          className="text-[9px] uppercase font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 select-none"
                        >
                          {run.status === 'queued'
                            ? 'QUEUED'
                            : run.status === 'running'
                              ? 'RUNNING'
                              : 'NO TRANSCRIPT'}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}

            {hasMoreRuns && (
              <div className="p-2 text-center">
                <button
                  type="button"
                  onClick={() => setRunsLimit((prev) => prev + 20)}
                  disabled={isRunsLoading}
                  className="text-[10px] font-mono px-3 py-1 border border-[#27272a] hover:border-terminal-amber hover:text-terminal-amber rounded text-zinc-400 transition-colors disabled:opacity-50"
                >
                  {isRunsLoading ? 'Loading…' : 'LOAD MORE'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
