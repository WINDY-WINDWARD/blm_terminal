'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  useCreateWorkflow,
  useUpdateWorkflow,
  useWorkflowPreview,
} from '@/hooks/useAiWorkflows';
import type {
  ScheduleType,
  Workflow,
  WorkflowCreateInput,
  WorkflowUpdateInput,
} from '@/types/aiWorkflowTypes';
import type { ModelOption } from '@/types/aiWidgetTypes';
import { AiPromptTextEditor } from '@/components/widgets/AiPromptTextEditor';
import { formatIst, toDateTimeLocalValue } from '@/lib/aiWorkflowTime';

export interface AiWorkflowEditorProps {
  workflow?: Workflow | null;
  models: ModelOption[];
  onCancel: () => void;
  onSaved: () => void;
}

const WEEKDAY_OPTIONS: { label: string; value: number }[] = [
  { label: 'Mon', value: 1 },
  { label: 'Tue', value: 2 },
  { label: 'Wed', value: 3 },
  { label: 'Thu', value: 4 },
  { label: 'Fri', value: 5 },
  { label: 'Sat', value: 6 },
  { label: 'Sun', value: 0 },
];

function defaultCatchUpHours(type: ScheduleType): number {
  switch (type) {
    case 'daily':
    case 'weekdays':
    case 'custom':
      return 12;
    case 'weekly':
    case 'once':
      return 24;
    case 'hourly':
      return 2;
    default:
      return 12;
  }
}

function parseDaysOfWeek(val: string | null | undefined): number[] {
  if (!val) return [1];
  const parsed = val
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => !Number.isNaN(n));
  return parsed.length > 0 ? parsed : [1];
}

function getDefaultOnceAt(): string {
  const d = new Date(Date.now() + 3600_000);
  d.setMinutes(0, 0, 0);
  return d.toISOString().slice(0, 16);
}

export function AiWorkflowEditor({
  workflow,
  models,
  onCancel,
  onSaved,
}: AiWorkflowEditorProps) {
  const isEditing = Boolean(workflow?.id);

  const [name, setName] = useState(workflow?.name ?? '');
  const [prompt, setPrompt] = useState(workflow?.prompt ?? '');
  const [scheduleType, setScheduleType] = useState<ScheduleType>(
    (workflow?.schedule_type as ScheduleType) || 'daily',
  );
  const [timeOfDay, setTimeOfDay] = useState(workflow?.time_of_day ?? '09:15');
  const [daysOfWeek, setDaysOfWeek] = useState<number[]>(() =>
    parseDaysOfWeek(workflow?.days_of_week),
  );
  const [onceAt, setOnceAt] = useState<string>(() => {
    if (workflow?.schedule_type === 'once' && workflow.next_run_at) {
      return toDateTimeLocalValue(workflow.next_run_at) || getDefaultOnceAt();
    }
    return getDefaultOnceAt();
  });
  const [cron, setCron] = useState(workflow?.cron_expression ?? '0 10 * * 1-5');
  const [model, setModel] = useState(workflow?.model ?? '');
  const [catchUpEnabled, setCatchUpEnabled] = useState(workflow?.catch_up_enabled ?? true);
  const [catchUpHours, setCatchUpHours] = useState<number>(
    workflow?.catch_up_window_hours ?? defaultCatchUpHours((workflow?.schedule_type as ScheduleType) || 'daily'),
  );
  const [allowWriteTools, setAllowWriteTools] = useState(workflow?.allow_write_tools ?? false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const createWorkflow = useCreateWorkflow();
  const updateWorkflow = useUpdateWorkflow();
  const previewMutation = useWorkflowPreview();
  const { mutate: previewWorkflow } = previewMutation;

  const isSaving = createWorkflow.isPending || updateWorkflow.isPending;

  const handleFrequencyChange = (newFreq: ScheduleType) => {
    setScheduleType(newFreq);
    setCatchUpHours(defaultCatchUpHours(newFreq));
  };

  const toggleDay = (day: number) => {
    setDaysOfWeek((prev) => {
      if (prev.includes(day)) {
        if (prev.length <= 1) return prev;
        return prev.filter((d) => d !== day);
      }
      return [...prev, day].sort((a, b) => a - b);
    });
  };

  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = setTimeout(() => {
      let onceIso: string | null = null;
      if (scheduleType === 'once' && onceAt) {
        try {
          onceIso = new Date(onceAt).toISOString();
        } catch {
          onceIso = null;
        }
      }

      previewWorkflow({
        schedule_type: scheduleType,
        time_of_day: ['daily', 'weekdays', 'weekly'].includes(scheduleType)
          ? timeOfDay
          : scheduleType === 'hourly'
            ? timeOfDay || null
            : null,
        days_of_week: scheduleType === 'weekly' ? daysOfWeek : null,
        cron: scheduleType === 'custom' ? cron : null,
        once_at: onceIso,
      });
    }, 400);

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [scheduleType, timeOfDay, daysOfWeek, onceAt, cron, previewWorkflow]);

  const handleSave = useCallback(async () => {
    const trimmedName = name.trim();
    const trimmedPrompt = prompt.trim();

    if (!trimmedName) {
      setErrorMessage('Name is required');
      return;
    }
    if (!trimmedPrompt) {
      setErrorMessage('Prompt is required');
      return;
    }

    let onceIso: string | null = null;
    if (scheduleType === 'once') {
      if (!onceAt) {
        setErrorMessage('Date and time is required for one-time schedule');
        return;
      }
      try {
        onceIso = new Date(onceAt).toISOString();
      } catch {
        setErrorMessage('Invalid date and time');
        return;
      }
    }

    if (scheduleType === 'custom' && !cron.trim()) {
      setErrorMessage('Cron expression is required for custom schedule');
      return;
    }

    setErrorMessage(null);

    try {
      if (isEditing && workflow?.id) {
        const updatePayload: WorkflowUpdateInput = {
          name: trimmedName,
          prompt: trimmedPrompt,
          schedule_type: scheduleType,
          time_of_day: ['daily', 'weekdays', 'weekly', 'hourly'].includes(scheduleType)
            ? timeOfDay
            : null,
          days_of_week: scheduleType === 'weekly' ? daysOfWeek : null,
          cron: scheduleType === 'custom' ? cron.trim() : null,
          once_at: onceIso,
          model: model || null,
          catch_up_enabled: catchUpEnabled,
          catch_up_window_hours: catchUpEnabled ? catchUpHours : null,
          allow_write_tools: allowWriteTools,
        };

        await updateWorkflow.mutateAsync({
          id: workflow.id,
          data: updatePayload,
        });
      } else {
        const createPayload: WorkflowCreateInput = {
          name: trimmedName,
          prompt: trimmedPrompt,
          schedule_type: scheduleType,
          time_of_day: ['daily', 'weekdays', 'weekly', 'hourly'].includes(scheduleType)
            ? timeOfDay
            : null,
          days_of_week: scheduleType === 'weekly' ? daysOfWeek : null,
          cron: scheduleType === 'custom' ? cron.trim() : null,
          once_at: onceIso,
          model: model || null,
          catch_up_enabled: catchUpEnabled,
          catch_up_window_hours: catchUpEnabled ? catchUpHours : null,
          allow_write_tools: allowWriteTools,
        };

        await createWorkflow.mutateAsync(createPayload);
      }
      onSaved();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save workflow';
      setErrorMessage(msg);
    }
  }, [
    name,
    prompt,
    scheduleType,
    timeOfDay,
    daysOfWeek,
    cron,
    onceAt,
    model,
    catchUpEnabled,
    catchUpHours,
    allowWriteTools,
    isEditing,
    workflow,
    updateWorkflow,
    createWorkflow,
    onSaved,
  ]);

  const previewRuns = previewMutation.data?.next_runs ?? [];

  const hasName = Boolean(name.trim());
  const hasPrompt = Boolean(prompt.trim());
  const isCronValid = scheduleType !== 'custom' || Boolean(cron.trim());
  const isOnceValid = scheduleType !== 'once' || Boolean(onceAt);

  let disabledReason: string | null = null;
  if (!hasName && !hasPrompt) {
    disabledReason = 'Add a name and prompt to save';
  } else if (!hasName || !hasPrompt) {
    disabledReason = 'Name and prompt required';
  } else if (!isCronValid) {
    disabledReason = 'Fix the cron expression';
  } else if (!isOnceValid) {
    disabledReason = 'Date and time required';
  }

  const isSaveDisabled = isSaving || !hasName || !hasPrompt || !isCronValid || !isOnceValid;

  return (
    <div className="flex flex-col min-h-full">
      <div className="flex flex-col gap-3 p-3 flex-1">
        {/* 1. NAME */}
        <div>
          <label
            htmlFor="wf-name"
            className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block"
          >
            Name
          </label>
          <input
            id="wf-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workflow name"
            disabled={isSaving}
            className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
          />
        </div>

        {/* 2. PROMPT */}
        <div>
          <AiPromptTextEditor
            value={prompt}
            onChange={setPrompt}
            saving={isSaving}
            label="Prompt"
            hideActions
          />
        </div>

        {/* 3. SCHEDULE */}
        <div className="flex flex-col gap-3">
          <div>
            <label
              htmlFor="wf-schedule"
              className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block"
            >
              Schedule
            </label>
            <select
              id="wf-schedule"
              value={scheduleType}
              onChange={(e) => handleFrequencyChange(e.target.value as ScheduleType)}
              disabled={isSaving}
              className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
            >
              <option value="daily">Daily</option>
              <option value="weekdays">Weekdays</option>
              <option value="weekly">Weekly</option>
              <option value="hourly">Hourly</option>
              <option value="once">Once</option>
              <option value="custom">Custom</option>
            </select>
          </div>

          {['daily', 'weekdays', 'weekly'].includes(scheduleType) && (
            <div>
              <label
                htmlFor="wf-time"
                className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block"
              >
                Time
              </label>
              <input
                id="wf-time"
                type="time"
                value={timeOfDay}
                onChange={(e) => setTimeOfDay(e.target.value)}
                disabled={isSaving}
                className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
              />
            </div>
          )}

          {scheduleType === 'weekly' && (
            <div>
              <label className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block">
                Weekdays
              </label>
              <div className="flex items-center gap-1">
                {WEEKDAY_OPTIONS.map((opt) => {
                  const active = daysOfWeek.includes(opt.value);
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => toggleDay(opt.value)}
                      disabled={isSaving}
                      className={cn(
                        'flex-1 py-1 text-[10px] font-mono rounded border transition-colors',
                        active
                          ? 'bg-terminal-amber text-black font-bold border-terminal-amber'
                          : 'bg-[#121216] text-zinc-400 border-[#27272a] hover:border-zinc-500',
                      )}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {scheduleType === 'once' && (
            <div>
              <label
                htmlFor="wf-once"
                className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block"
              >
                Date and Time
              </label>
              <input
                id="wf-once"
                type="datetime-local"
                value={onceAt}
                onChange={(e) => setOnceAt(e.target.value)}
                disabled={isSaving}
                className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
              />
            </div>
          )}

          {scheduleType === 'custom' && (
            <div>
              <label
                htmlFor="wf-cron"
                className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block"
              >
                Cron
              </label>
              <input
                id="wf-cron"
                type="text"
                value={cron}
                onChange={(e) => setCron(e.target.value)}
                placeholder="0 10 * * 1-5"
                disabled={isSaving}
                className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
              />
            </div>
          )}

          <div className="text-[10px] font-mono text-zinc-500">
            Scope comes from the prompt. Mention symbols, a watchlist, or the whole market.
          </div>
        </div>

        {/* 4. PREVIEW LINE */}
        <div className="p-2 bg-[#121216] border border-[#27272a] rounded-md text-[11px] font-mono text-zinc-400">
          <span className="text-zinc-500">Next: </span>
          {previewMutation.isPending ? (
            <span className="text-zinc-500">calculating…</span>
          ) : previewRuns.length > 0 ? (
            <span className="text-zinc-300">
              {previewRuns.map((r) => formatIst(r)).filter(Boolean).join(', ')}
            </span>
          ) : (
            <span className="text-zinc-500">—</span>
          )}
        </div>

        {/* 5. ADVANCED */}
        <div className="pt-1">
          <button
            type="button"
            onClick={() => setAdvancedOpen((prev) => !prev)}
            className="flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            <span>{advancedOpen ? '▾' : '▸'}</span>
            <span>ADVANCED</span>
          </button>
          {advancedOpen && (
            <div className="flex flex-col gap-3 mt-2">
              <div>
                <label
                  htmlFor="wf-model"
                  className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 mb-1 block"
                >
                  Model
                </label>
                <select
                  id="wf-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  disabled={isSaving}
                  className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
                >
                  <option value="">App default</option>
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex flex-col gap-2 pt-1 border-t border-[#27272a]/60">
                <div className="flex items-center justify-between gap-2">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={catchUpEnabled}
                      onChange={(e) => setCatchUpEnabled(e.target.checked)}
                      disabled={isSaving}
                      className="rounded border-[#27272a] bg-[#121216] text-terminal-amber focus:ring-0"
                    />
                    <span className="text-xs font-mono text-zinc-300">Catch up if missed</span>
                  </label>
                  {catchUpEnabled && (
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        min={1}
                        max={168}
                        value={catchUpHours}
                        onChange={(e) => setCatchUpHours(Math.max(1, Number(e.target.value)))}
                        disabled={isSaving}
                        className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-0.5 w-14 text-right outline-none"
                      />
                      <span className="text-[10px] font-mono text-zinc-500">h</span>
                    </div>
                  )}
                </div>

                <div>
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={allowWriteTools}
                      onChange={(e) => setAllowWriteTools(e.target.checked)}
                      disabled={isSaving}
                      className="rounded border-[#27272a] bg-[#121216] text-terminal-amber focus:ring-0"
                    />
                    <span className="text-xs font-mono text-zinc-300">Allow actions</span>
                  </label>
                  <div className="text-[10px] font-mono text-zinc-500 ml-5 mt-0.5">
                    Orders, watchlists, positions
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Error message */}
        {errorMessage && (
          <div className="text-[11px] font-mono text-red-400">{errorMessage}</div>
        )}
      </div>

      {/* 6. STICKY FOOTER */}
      <div className="sticky bottom-0 z-10 border-t border-[#27272a] bg-[#0c0c0f] px-3 py-2 flex items-center gap-2">
        <div className="flex-1 text-[11px] font-mono text-zinc-500 truncate">
          {disabledReason}
        </div>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={isSaveDisabled}
          className="py-1.5 px-3 bg-terminal-amber hover:bg-terminal-amber/80 text-black font-mono font-bold text-xs rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
        >
          {isSaving ? 'Saving...' : 'SAVE'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={isSaving}
          className="py-1.5 px-3 border border-[#27272a] text-zinc-300 hover:text-white hover:border-zinc-500 font-mono text-xs rounded transition-colors shrink-0"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
