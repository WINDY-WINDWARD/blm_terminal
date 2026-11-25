export type ScheduleType = 'daily' | 'weekdays' | 'weekly' | 'hourly' | 'once' | 'custom';

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface Workflow {
  id: number;
  name: string;
  description: string | null;
  prompt: string;
  schedule_type: string;
  cron_expression: string;
  timezone: string;
  time_of_day: string | null;
  days_of_week: string | null;
  symbols: string[];
  watchlist_id: number | null;
  model: string | null;
  persona: string | null;
  mode: string;
  allow_write_tools: boolean;
  is_enabled: boolean;
  catch_up_enabled: boolean;
  catch_up_window_hours: number;
  next_run_at: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  schedule_label: string;
  created_at: string;
}

export interface WorkflowRun {
  id: number;
  workflow_id: number;
  trigger: string;
  status: string;
  skip_reason: string | null;
  scheduled_for: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  session_id: number | null;
  output_summary: string | null;
  error: string | null;
  attempt: number;
  is_read: boolean;
  is_silent: boolean;
  name_snapshot: string | null;
  created_at: string;
}

export interface CustomPrompt {
  id: number;
  title: string;
  tag: string;
  description: string | null;
  prompt: string;
  icon: string | null;
  mode: string;
  sort_order: number;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
}

export interface WorkflowSummary {
  armed: number;
  unread: number;
  running: number;
  next_run_at: string | null;
  server_now: string;
}

export interface WorkflowPreview {
  cron_expression: string;
  schedule_label: string;
  next_runs: string[];
}

export interface WorkflowCreateInput {
  name: string;
  prompt: string;
  schedule_type: ScheduleType;
  time_of_day?: string | null;
  days_of_week?: number[] | null;
  cron?: string | null;
  once_at?: string | null;
  symbols?: string[] | null;
  watchlist_id?: number | null;
  model?: string | null;
  persona?: string | null;
  catch_up_enabled?: boolean;
  catch_up_window_hours?: number | null;
  allow_write_tools?: boolean;
}

export interface WorkflowUpdateInput {
  name?: string | null;
  prompt?: string | null;
  schedule_type?: ScheduleType | null;
  time_of_day?: string | null;
  days_of_week?: number[] | null;
  cron?: string | null;
  once_at?: string | null;
  symbols?: string[] | null;
  watchlist_id?: number | null;
  model?: string | null;
  persona?: string | null;
  catch_up_enabled?: boolean | null;
  catch_up_window_hours?: number | null;
  allow_write_tools?: boolean | null;
  is_enabled?: boolean | null;
}

export interface WorkflowPreviewInput {
  schedule_type: ScheduleType;
  time_of_day?: string | null;
  days_of_week?: number[] | null;
  cron?: string | null;
  once_at?: string | null;
  timezone?: string;
}

export interface PromptCreateInput {
  title: string;
  tag: string;
  description?: string | null;
  prompt: string;
  icon?: string | null;
  mode?: 'research' | 'script' | string;
}

export interface PromptUpdateInput {
  title?: string | null;
  tag?: string | null;
  description?: string | null;
  prompt?: string | null;
  icon?: string | null;
  mode?: 'research' | 'script' | string | null;
  sort_order?: number | null;
}

export interface WorkflowCardPayload {
  type: string;
  id?: number;
  name?: string;
  title?: string;
  prompt?: string;
  schedule_label?: string;
  next_run_at?: string | null;
  symbols?: string[];
  status: 'created' | 'proposed';
  changes?: Record<string, unknown>;
  previous?: Record<string, unknown>;
  dismissed?: boolean;
}

export interface PromptCardPayload {
  type: string;
  id?: number;
  title?: string;
  name?: string;
  prompt?: string;
  schedule_label?: string;
  next_run_at?: string | null;
  symbols?: string[];
  status: 'created' | 'proposed';
  changes?: Record<string, unknown>;
  previous?: Record<string, unknown>;
  dismissed?: boolean;
}
