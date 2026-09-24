/**
 * BLM Script Lab v1 — frontend client for the backend scripts API.
 * All routes go through the Next.js python proxy (/api/py/*).
 */
import type {
  SavedScriptDetail,
  SavedScriptSummary,
  ScriptChartSlot,
} from './types';

const BASE = '/api/py/scripts';

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const data = (await res.json().catch(() => ({}))) as { error?: string } & T;
  if (!res.ok) {
    throw new Error(
      typeof data?.error === 'string' ? data.error : `scripts API ${res.status}`,
    );
  }
  return data as T;
}

export function fetchScripts(): Promise<SavedScriptSummary[]> {
  return req<SavedScriptSummary[]>('');
}

export function fetchScriptDetail(id: number): Promise<SavedScriptDetail> {
  return req<SavedScriptDetail>(`/${id}`);
}

export function fetchChartState(panelId: string): Promise<ScriptChartSlot[]> {
  return req<ScriptChartSlot[]>(`/chart-state?panel_id=${encodeURIComponent(panelId)}`);
}

export interface ChartSlotSet {
  script_id: number;
  enabled: boolean;
  param_values: Record<string, number | boolean | string>;
}

export function setChartSlot(panelId: string, slot: ChartSlotSet): Promise<ScriptChartSlot> {
  return req<ScriptChartSlot>(`/chart-state?panel_id=${encodeURIComponent(panelId)}`, {
    method: 'POST',
    body: JSON.stringify(slot),
  });
}
