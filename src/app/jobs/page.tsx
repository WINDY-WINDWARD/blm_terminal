'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useAtom } from 'jotai';
import { authAtom } from '@/store/terminalStore';

interface Job {
  job_key: string;
  name: string;
  description: string | null;
  category: string | null;
  cron_expression: string | null;
  status: string;
  progress_percent: number;
  progress_message: string | null;
  last_triggered_at: string | null;
  last_completed_at: string | null;
  next_trigger_at: string | null;
  last_error: string | null;
  is_enabled: boolean;
  is_manual_only: boolean;
}

interface StockUniverseErrorSymbol {
  symbol: string;
  companyName: string | null;
  reviewStatus: string;
  series: string | null;
  lastUpdateTime: string | null;
}

interface ErrorCategory {
  count: number;
  symbols: StockUniverseErrorSymbol[];
}

interface SymbolErrors {
  delisted: ErrorCategory;
  illiquid: ErrorCategory;
  suspended: ErrorCategory;
  not_tradable: ErrorCategory;
  unknown: ErrorCategory;
}

interface IntradayIntervalStatus {
  total_rows: number;
  watchlist_covered: number;
  watchlist_current: number;
  symbols_with_indicators: number;
  latest_timestamp: string | null;
  universe_covered: number;
  universe_symbols_with_indicators: number;
}

interface DbQueueDetail {
  queue_size: number;
  queue_max: number;
  occupancy_pct: number;
  contended: boolean;
  per_prio?: Record<string, number>;
  oldest_wait_ms?: number;
}

interface DbStatsLive {
  occupancy: { size: number; max: number; pct: number };
  queue_detail: DbQueueDetail;
  throughput: {
    counters: { enqueued: number; executed: number; dropped: number };
    per_prio: Record<string, { enqueued: number; executed: number }>;
    records_per_min: number;
    batches_per_min: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    avg_queue_wait_ms: number;
    batches_sampled: number;
  };
  db: { db_bytes: number; wal_bytes: number; shm_bytes: number; total_bytes: number };
  writer: { alive: boolean; uptime_s: number | null };
  recent_alerts: { ts: number; type: string; severity: string }[];
  history: { ts: number; occupancy_pct: number | null; records_per_min: number; avg_latency_ms: number }[];
}

interface DbAlert {
  id: number | string;
  ts: number;
  type: string;
  severity: string;
  message: string;
  snapshot: Record<string, unknown>;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let v = bytes / 1024;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return `${v.toFixed(1)} ${units[u]}`;
}

function formatEpoch(ts: number | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

const PRIO_LABELS: Record<string, string> = {
  '-1': 'UI',
  '0': 'Jobs',
  '1': 'API cache',
  '2': 'Notifications',
  '3': 'Bulk data',
};

interface TickerStatus {
  total_rows: number;
  symbols_covered: number;
  symbols_current: number;
  symbols_stale: number;
  universe_count: number;
  last_trading_day: string | null;
  latest_date: string | null;
  last_update_time: string | null;
  backfill_pending: number;
  backfill_progress_percent: number;
  watchlist_symbols_covered: number;
  watchlist_symbols_total: number;
  watchlist_symbols_current: number;
  days_behind_breakdown: Record<string, number>;
  intraday_stats: Record<string, IntradayIntervalStatus>;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const date = new Date(dateStr);
  return date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

const orchestratorScheduleLabels: Record<string, string> = {
  'job.ticker_intraday_hourly_stale_check': 'Startup + nightly pipeline',
  'job.ticker_weekly_monthly_update': 'Nightly pipeline (23:00 IST)',
  'job.ticker_weekly_monthly_indicators': 'Nightly pipeline (23:00 IST)',
};

function formatCron(expr: string | null | undefined, jobKey: string): string {
  if (!expr) return orchestratorScheduleLabels[jobKey] ?? '—';
  const map: Record<string, string> = {
    '@startup':          'Run once (startup)',
    '0 0 * * *':         'Daily midnight',
    '0 11 * * 1-5':      'Weekdays 11:00',
    '30 10,14 * * 1-5':  'Weekdays 10:30 & 14:30',
    '0 8,14 * * 1-5':    'Weekdays 08:00 & 14:00',
    '*/30 15,16,17,18,19,20 * * 1-5': 'Weekdays every 30min 15:00–20:30',
    '*/5 * * * *':       'Every 5 min',
    '*/30 * * * *':      'Every 30 min',
    '0 */3 * * *':       'Every 3 hours',
    '30 20 * * *':       'Daily 20:30 UTC',
    '0 23 * * *':        'Daily 23:00 IST',
    '30 23 * * *':       'Daily 23:30 IST',
  };
  return map[expr] ?? expr;
}

function formatNextTrigger(dateStr: string | null, isManualOnly: boolean, jobKey: string): string {
  if (isManualOnly) return 'Manual only';
  if (!dateStr) {
    if (jobKey === 'job.ticker_intraday_hourly_stale_check') {
      return 'At startup and 23:00 IST nightly';
    }
    if (jobKey === 'job.ticker_weekly_monthly_update' || jobKey === 'job.ticker_weekly_monthly_indicators') {
      return 'Startup + nightly pipeline at 23:00 IST';
    }
    return '—';
  }
  const date = new Date(dateStr);
  const now = Date.now();
  const diffMs = date.getTime() - now;
  if (diffMs <= 0) return 'Pending...';
  const abs = date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const mins = Math.round(diffMs / 60000);
  if (mins < 60) return `${abs} (in ${mins}m)`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${abs} (in ${hours}h)`;
  const days = Math.round(hours / 24);
  return `${abs} (in ${days}d)`;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    idle: 'text-terminal-green bg-terminal-green/10',
    running: 'text-blue-400 bg-blue-400/10',
    waiting: 'text-terminal-amber bg-terminal-amber/10',
    failed: 'text-terminal-red bg-terminal-red/10',
  };
  const color = colors[status] || 'text-white bg-white/10';
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${color}`}>
      {status}
    </span>
  );
}

function OccupancyBar({ size, max, pct }: { size: number; max: number; pct: number }) {
  const color =
    pct >= 90 ? 'bg-terminal-red' : pct >= 70 ? 'bg-terminal-amber' : 'bg-terminal-green';
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <div className="text-2xl font-bold text-white">
          {size.toLocaleString()}
          <span className="text-sm text-white/50">/{max.toLocaleString()}</span>
        </div>
        <div className={`text-lg font-bold ${pct >= 90 ? 'text-terminal-red' : pct >= 70 ? 'text-terminal-amber' : 'text-terminal-green'}`}>
          {pct.toFixed(1)}%
        </div>
      </div>
      <div className="w-full h-2 bg-terminal-gray rounded overflow-hidden mt-2">
        <div className={`h-full transition-[width] ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <div className="flex justify-between text-[10px] text-white/40 mt-1">
        <span>warn ≥70% (3,500)</span>
        <span>critical ≥90% (4,500)</span>
      </div>
    </div>
  );
}

function Sparkline({ points, color }: { points: (number | null)[]; color: string }) {
  const vals = points.filter((v): v is number => v !== null && v !== undefined);
  const max = Math.max(...vals, 1);
  return (
    <div className="flex items-end gap-[2px] h-10 mt-2">
      {points.map((v, i) => (
        <div
          key={i}
          className={`flex-1 rounded-sm ${v === null || v === undefined ? 'bg-white/5' : color}`}
          style={{ height: `${v === null || v === undefined ? 8 : Math.max(8, (v / max) * 100)}%` }}
          title={v === null || v === undefined ? 'no data' : String(v)}
        />
      ))}
    </div>
  );
}

function DbStatsPanel({
  live,
  liveError,
  alerts,
  alertsError,
  expandedAlert,
  setExpandedAlert,
}: {
  live: DbStatsLive | null;
  liveError: string | null;
  alerts: DbAlert[];
  alertsError: string | null;
  expandedAlert: string | number | null;
  setExpandedAlert: (v: string | number | null) => void;
}) {
  if (liveError && !live) {
    return (
      <div className="p-3 bg-terminal-red/10 border border-terminal-red text-terminal-red text-xs">
        {liveError}
      </div>
    );
  }
  if (!live) {
    return <div className="text-terminal-amber">Loading...</div>;
  }
  const occ = live.occupancy;
  const tp = live.throughput;
  const perPrio = live.queue_detail.per_prio || {};
  return (
    <div className="space-y-4">
      {/* Row 1: occupancy + throughput + db size */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="p-3 rounded border border-terminal-gray/20 bg-terminal-gray/10">
          <div className="text-[10px] text-white/60 uppercase tracking-wider mb-2">
            Queue Occupancy {!live.writer.alive && <span className="text-terminal-red">(writer down)</span>}
          </div>
          <OccupancyBar size={occ.size} max={occ.max} pct={occ.pct} />
          {Object.keys(perPrio).length > 0 && (
            <div className="mt-2 space-y-0.5">
              {Object.entries(perPrio)
                .sort((a, b) => Number(a[0]) - Number(b[0]))
                .map(([prio, n]) => (
                  <div key={prio} className="flex justify-between text-[10px] text-white/50">
                    <span>{PRIO_LABELS[prio] ?? `prio ${prio}`}</span>
                    <span className="text-white/80">{n}</span>
                  </div>
                ))}
            </div>
          )}
          {live.queue_detail.contended && (
            <div className="text-[10px] text-white/40 mt-1">breakdown contended — size only</div>
          )}
        </div>

        <div className="p-3 rounded border border-terminal-gray/20 bg-terminal-gray/10">
          <div className="text-[10px] text-white/60 uppercase tracking-wider mb-2">Write Speed</div>
          <div className="grid grid-cols-2 gap-2 text-center">
            <div>
              <div className="text-xl font-bold text-white">{tp.records_per_min.toLocaleString()}</div>
              <div className="text-[10px] text-white/50">records/min</div>
            </div>
            <div>
              <div className="text-xl font-bold text-white">{tp.avg_latency_ms.toFixed(1)}</div>
              <div className="text-[10px] text-white/50">avg latency ms</div>
            </div>
            <div>
              <div className="text-xl font-bold text-white">{tp.p95_latency_ms.toFixed(1)}</div>
              <div className="text-[10px] text-white/50">p95 latency ms</div>
            </div>
            <div>
              <div className="text-xl font-bold text-white">{tp.avg_queue_wait_ms.toFixed(0)}</div>
              <div className="text-[10px] text-white/50">avg queue wait ms</div>
            </div>
          </div>
          <div className="text-[10px] text-white/40 mt-2">
            {tp.counters.executed.toLocaleString()} executed · {tp.counters.dropped.toLocaleString()} dropped · {tp.batches_per_min.toLocaleString()} batches/min
          </div>
          <Sparkline points={live.history.map((h) => h.records_per_min)} color="bg-terminal-amber/70" />
        </div>

        <div className="p-3 rounded border border-terminal-gray/20 bg-terminal-gray/10">
          <div className="text-[10px] text-white/60 uppercase tracking-wider mb-2">Database Size</div>
          <div className="text-2xl font-bold text-white">{formatBytes(live.db.total_bytes)}</div>
          <div className="mt-2 space-y-0.5 text-[10px]">
            <div className="flex justify-between text-white/50">
              <span>main db</span>
              <span className="text-white/80">{formatBytes(live.db.db_bytes)}</span>
            </div>
            <div className="flex justify-between text-white/50">
              <span>WAL</span>
              <span className="text-white/80">{formatBytes(live.db.wal_bytes)}</span>
            </div>
            <div className="flex justify-between text-white/50">
              <span>SHM</span>
              <span className="text-white/80">{formatBytes(live.db.shm_bytes)}</span>
            </div>
            <div className="flex justify-between text-white/50">
              <span>writer uptime</span>
              <span className="text-white/80">{live.writer.uptime_s !== null ? `${Math.round(live.writer.uptime_s)}s` : '—'}</span>
            </div>
          </div>
          <Sparkline points={live.history.map((h) => h.avg_latency_ms)} color="bg-blue-400/70" />
        </div>
      </div>

      {/* Row 2: DB alerts (silent — only visible here) */}
      <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
        <div className="flex items-center justify-between mb-3">
          <div className="text-[10px] text-white/60 uppercase tracking-wider">
            DB Alerts <span className="text-white/40 normal-case">(silent — queue/latency spikes only)</span>
          </div>
          <div className="text-[10px] text-white/40">
            {alertsError ? 'Failed to load' : `${alerts.length} recorded`}
          </div>
        </div>
        {alerts.length === 0 ? (
          <div className="text-[10px] text-terminal-green py-2 text-center">
            No alerts — queue healthy
          </div>
        ) : (
          <div className="space-y-1">
            {alerts.map((a) => {
              const expanded = expandedAlert === a.id;
              const sevColor =
                a.severity === 'critical' ? 'text-terminal-red border-terminal-red/40' : 'text-terminal-amber border-terminal-amber/40';
              return (
                <div key={String(a.id)} className={`border rounded ${sevColor} bg-black/20`}>
                  <button
                    onClick={() => setExpandedAlert(expanded ? null : a.id)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 text-left"
                  >
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${a.severity === 'critical' ? 'bg-terminal-red/20' : 'bg-terminal-amber/20'}`}>
                      {a.severity}
                    </span>
                    <span className="text-[10px] text-white/40 whitespace-nowrap">{formatEpoch(a.ts)}</span>
                    <span className="text-[10px] text-white/80 truncate flex-1">{a.message}</span>
                    <span className="text-white/50 text-[10px]">{expanded ? '▾' : '▸'}</span>
                  </button>
                  {expanded && (
                    <div className="px-2 pb-2">
                      <div className="text-[10px] text-white/40 mb-1">Queue snapshot at event time:</div>
                      <pre className="text-[10px] text-white/70 bg-black/40 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(a.snapshot, null, 1)}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<'jobs' | 'stats' | 'dbstats'>('jobs');
  const [tickerStatus, setTickerStatus] = useState<TickerStatus | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [dbLive, setDbLive] = useState<DbStatsLive | null>(null);
  const [dbLiveError, setDbLiveError] = useState<string | null>(null);
  const [dbAlerts, setDbAlerts] = useState<DbAlert[]>([]);
  const [dbAlertsError, setDbAlertsError] = useState<string | null>(null);
  const [expandedAlert, setExpandedAlert] = useState<string | number | null>(null);
  const [symbolErrors, setSymbolErrors] = useState<SymbolErrors | null>(null);
  const [errorsLoading, setErrorsLoading] = useState(false);
  const [changeSymbolInput, setChangeSymbolInput] = useState<string>('');
  const [changingSymbol, setChangingSymbol] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const [auth] = useAtom(authAtom);
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  const openLogs = useCallback(() => {
    window.open('/logs?lines=200', 'blm_logs', 'width=900,height=520,scrollbars=yes,resizable=yes');
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch('/api/jobs');
      if (!res.ok) throw new Error('Failed to fetch jobs');
      const data = await res.json();
      setJobs(data.jobs);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch jobs:', err);
      setError('Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 5000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const handleTrigger = async (jobKey: string) => {
    setTriggering(jobKey);
    try {
      const res = await fetch(`/api/jobs/${jobKey}/trigger`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        alert(data.error || 'Failed to trigger job');
      } else {
        await fetchJobs();
      }
    } catch (err) {
      console.error('Failed to trigger job:', err);
      alert('Failed to trigger job');
    } finally {
      setTriggering(null);
    }
  };

  const handleToggle = async (jobKey: string, enabled: boolean) => {
    setToggling(jobKey);
    try {
      const res = await fetch(`/api/jobs/${jobKey}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(data.error || 'Failed to toggle job');
      } else {
        await fetchJobs();
      }
    } catch (err) {
      console.error('Failed to toggle job:', err);
      alert('Failed to toggle job');
    } finally {
      setToggling(null);
    }
  };

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const res = await fetch('/api/py/ticker/status');
      if (!res.ok) throw new Error('Failed to fetch ticker status');
      const data = await res.json();
      setTickerStatus(data);
    } catch (err) {
      console.error('Failed to fetch ticker status:', err);
      setStatsError('Failed to load ticker stats');
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const fetchSymbolErrors = useCallback(async () => {
    setErrorsLoading(true);
    try {
      const res = await fetch('/api/stockuniverse/errors');
      if (!res.ok) throw new Error('Failed to fetch symbol errors');
      const data = await res.json();
      setSymbolErrors(data);
    } catch (err) {
      console.error('Failed to fetch symbol errors:', err);
    } finally {
      setErrorsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab !== 'stats') return;
    fetchStats();
    fetchSymbolErrors();
    const interval = setInterval(() => {
      fetchStats();
      fetchSymbolErrors();
    }, 10000);
    return () => clearInterval(interval);
  }, [activeTab, fetchStats, fetchSymbolErrors]);

  const fetchDbLive = useCallback(async () => {
    try {
      const res = await fetch('/api/jobs/db-stats/live');
      if (!res.ok) throw new Error('Failed to fetch DB stats');
      const data = await res.json();
      setDbLive(data);
      setDbLiveError(null);
    } catch (err) {
      console.error('Failed to fetch DB stats:', err);
      setDbLiveError('Failed to load DB stats');
    }
  }, []);

  const fetchDbAlerts = useCallback(async () => {
    try {
      const res = await fetch('/api/jobs/db-stats/alerts?limit=100');
      if (!res.ok) throw new Error('Failed to fetch DB alerts');
      const data = await res.json();
      setDbAlerts(data.alerts || []);
      setDbAlertsError(null);
    } catch (err) {
      console.error('Failed to fetch DB alerts:', err);
      setDbAlertsError('Failed to load DB alerts');
    }
  }, []);

  useEffect(() => {
    if (activeTab !== 'dbstats') return;
    fetchDbLive();
    fetchDbAlerts();
    const liveInterval = setInterval(fetchDbLive, 2000);
    const alertsInterval = setInterval(fetchDbAlerts, 10000);
    return () => {
      clearInterval(liveInterval);
      clearInterval(alertsInterval);
    };
  }, [activeTab, fetchDbLive, fetchDbAlerts]);

  const handleTriggerBackfill = async () => {
    if (!confirm('Trigger full backfill for all watchlist symbols?')) return;
    try {
      const res = await fetch('/api/py/ticker/trigger-backfill', { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        alert(data.error || 'Failed to trigger backfill');
      } else {
        await fetchStats();
      }
    } catch (err) {
      console.error('Failed to trigger backfill:', err);
      alert('Failed to trigger backfill');
    }
  };

  const handleTriggerDailyUpdate = async () => {
    if (!confirm('Trigger daily update for today\'s data?')) return;
    try {
      const res = await fetch('/api/py/ticker/trigger-daily-update', { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        alert(data.error || 'Failed to trigger daily update');
      } else {
        await fetchStats();
      }
    } catch (err) {
      console.error('Failed to trigger daily update:', err);
      alert('Failed to trigger daily update');
    }
  };

  const handleRemoveSymbol = async (symbol: string) => {
    if (!confirm(`Remove symbol ${symbol}? This will delete all its ticker data.`)) return;
    try {
      const res = await fetch(`/api/stockuniverse/errors/${symbol}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Failed to remove symbol');
      } else {
        await fetchSymbolErrors();
      }
    } catch (err) {
      console.error('Failed to remove symbol:', err);
      alert('Failed to remove symbol');
    }
  };

  const handleChangeSymbol = async (oldSymbol: string) => {
    const newSymbol = changeSymbolInput.trim().toUpperCase();
    if (!newSymbol) {
      alert('Enter a new symbol');
      return;
    }
    setChangingSymbol(oldSymbol);
    try {
      const res = await fetch(`/api/stockuniverse/errors/${oldSymbol}/change-symbol`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ newSymbol }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Failed to change symbol');
      } else {
        setChangeSymbolInput('');
        await fetchSymbolErrors();
      }
    } catch (err) {
      console.error('Failed to change symbol:', err);
      alert('Failed to change symbol');
    } finally {
      setChangingSymbol(null);
    }
  };

  if (!mounted) return <div className="h-screen bg-terminal-bg" />;
  if (!auth || !auth.user.is_admin) {
    return (
      <div className="h-screen bg-terminal-bg flex flex-col items-center justify-center text-center p-4 font-mono">
        <div className="border border-terminal-red p-8 max-w-lg bg-terminal-panel shadow-xl shadow-red-900/20">
          <h2 className="text-3xl text-terminal-red font-bold mb-4 tracking-widest">ACCESS DENIED</h2>
          <p className="text-terminal-amber text-sm mb-6">You must be an administrator to view this page.</p>
          <Link href="/" className="inline-block border border-terminal-gray px-4 py-2 text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors font-bold">
            ← RETURN TO TERMINAL
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto bg-terminal-bg text-white font-mono p-4">
      <div className="w-full">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 border-b border-terminal-gray pb-2">
          <div>
            <h1 className="text-2xl text-terminal-amber font-bold">JOBS</h1>
            <p className="text-xs text-white/60">
              {activeTab === 'jobs'
                ? 'Background task management'
                : activeTab === 'stats'
                ? 'Ticker warehouse statistics'
                : 'Write-queue occupancy, throughput & silent alerts'}
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/"
              className="px-3 py-1 text-xs border border-terminal-gray text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors"
            >
              ← BACK
            </Link>
            <button
              onClick={activeTab === 'stats' ? fetchStats : activeTab === 'dbstats' ? fetchDbLive : fetchJobs}
              className="px-3 py-1 text-xs border border-terminal-gray text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors"
            >
              REFRESH
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-4">
          <button
            onClick={() => setActiveTab('jobs')}
            className={`px-4 py-2 text-xs font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'jobs'
                ? 'bg-terminal-amber text-terminal-bg'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            Jobs
          </button>
          <button
            onClick={() => setActiveTab('stats')}
            className={`px-4 py-2 text-xs font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'stats'
                ? 'bg-terminal-amber text-terminal-bg'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            Stats
          </button>
          <button
            onClick={() => setActiveTab('dbstats')}
            className={`px-4 py-2 text-xs font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'dbstats'
                ? 'bg-terminal-amber text-terminal-bg'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            DB Stats
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-terminal-red/10 border border-terminal-red text-terminal-red text-xs">
            {error}
          </div>
        )}

        {activeTab === 'jobs' ? (
          loading ? (
            <div className="text-terminal-amber">Loading...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-terminal-gray text-terminal-amber uppercase text-[10px] tracking-widest">
                    <th className="text-left py-2 px-2">Job</th>
                    <th className="text-left py-2 px-2">Category</th>
                    <th className="text-left py-2 px-2">Schedule</th>
                    <th className="text-left py-2 px-2">Status</th>
                    <th className="text-right py-2 px-2">Progress</th>
                    <th className="text-left py-2 px-2">Last Triggered</th>
                    <th className="text-left py-2 px-2">Last Completed</th>
                    <th className="text-left py-2 px-2">Next Trigger</th>
                    <th className="text-left py-2 px-2">Last Error</th>
                    <th className="text-center py-2 px-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr
                      key={job.job_key}
                      className="border-b border-terminal-gray/30 hover:bg-white/5"
                    >
                      <td className="py-2 px-2">
                        <div className="text-white font-bold">{job.name}</div>
                        <div className="text-white/50 text-[10px]">{job.description}</div>
                      </td>
                      <td className="py-2 px-2 text-white/70">{job.category || '—'}</td>
                      <td className="py-2 px-2 text-white/60 text-[10px] whitespace-nowrap">
                        {formatCron(job.cron_expression, job.job_key)}
                      </td>
                      <td className="py-2 px-2">
                        <StatusBadge status={job.status} />
                      </td>
                      <td className="py-2 px-2 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-24 h-1.5 bg-terminal-gray rounded overflow-hidden">
                            <div
                              className={`h-full transition-[width,background-color,color,transform] ${
                                job.status === 'failed'
                                  ? 'bg-terminal-red'
                                  : job.status === 'running'
                                  ? 'bg-blue-400'
                                  : 'bg-terminal-green'
                              }`}
                              style={{ width: `${job.progress_percent}%` }}
                            />
                          </div>
                          <span className="text-[10px] w-8 text-right">{job.progress_percent}%</span>
                        </div>
                        {job.progress_message && (
                          <div className="text-[10px] text-white/50 text-right mt-0.5">
                            {job.progress_message}
                          </div>
                        )}
                      </td>
                      <td className="py-2 px-2 text-white/70">{formatDate(job.last_triggered_at)}</td>
                      <td className="py-2 px-2 text-white/70">{formatDate(job.last_completed_at)}</td>
                      <td className="py-2 px-2 text-white/70">{formatNextTrigger(job.next_trigger_at, job.cron_expression === '@startup', job.job_key)}</td>
                      <td className="py-2 px-2 text-terminal-red text-[10px] max-w-[150px] truncate" title={job.last_error || ''}>
                        {job.last_error || '—'}
                      </td>
                      <td className="py-2 px-2">
                        <div className="flex gap-1 justify-center">
                          <button
                            onClick={() => handleTrigger(job.job_key)}
                            disabled={triggering === job.job_key || job.status === 'running'}
                            className="px-2 py-1 text-[10px] bg-terminal-amber/10 text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg active:scale-[0.96] disabled:opacity-30 disabled:cursor-not-allowed transition-[width,background-color,color,transform]"
                          >
                            {triggering === job.job_key ? 'STARTING...' : 'RUN'}
                          </button>
                          <button
                            onClick={() => handleToggle(job.job_key, !job.is_enabled)}
                            disabled={toggling === job.job_key}
                            className={`px-2 py-1 text-[10px] transition-[width,background-color,color,transform] active:scale-[0.96] ${
                              job.is_enabled
                                ? 'bg-terminal-red/10 text-terminal-red hover:bg-terminal-red hover:text-white disabled:opacity-30 disabled:cursor-wait'
                                : 'bg-terminal-green/10 text-terminal-green hover:bg-terminal-green hover:text-terminal-bg disabled:opacity-30 disabled:cursor-wait'
                            }`}
                          >
                            {toggling === job.job_key ? 'UPDATING...' : job.is_enabled ? 'DISABLE' : 'ENABLE'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : activeTab === 'dbstats' ? (
          <DbStatsPanel
            live={dbLive}
            liveError={dbLiveError}
            alerts={dbAlerts}
            alertsError={dbAlertsError}
            expandedAlert={expandedAlert}
            setExpandedAlert={setExpandedAlert}
          />
        ) : (
          <div>
            {statsLoading && !tickerStatus ? (
              <div className="text-terminal-amber">Loading...</div>
            ) : statsError ? (
              <div className="p-3 bg-terminal-red/10 border border-terminal-red text-terminal-red text-xs">
                {statsError}
              </div>
            ) : tickerStatus ? (
              <div className="space-y-4">
                {/* Row 1: Data freshness status */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {/* Expected date vs actual */}
                  <div className={`p-3 rounded border ${
                    tickerStatus.latest_date === tickerStatus.last_trading_day
                      ? 'bg-terminal-green/5 border-terminal-green/30'
                      : 'bg-terminal-red/5 border-terminal-red/30'
                  }`}>
                    <div className="text-[10px] text-white/60 uppercase tracking-wider">Expected Date</div>
                    <div className="text-lg text-white font-bold mt-1">
                      {tickerStatus.last_trading_day || '—'}
                    </div>
                    <div className={`text-[10px] mt-0.5 ${
                      tickerStatus.latest_date === tickerStatus.last_trading_day
                        ? 'text-terminal-green'
                        : 'text-terminal-red'
                    }`}>
                      {tickerStatus.latest_date === tickerStatus.last_trading_day
                        ? 'Up to date'
                        : `Latest: ${tickerStatus.latest_date || 'none'}`}
                    </div>
                  </div>

                  {/* Current symbols */}
                  <div className={`p-3 rounded border ${
                    tickerStatus.symbols_current === tickerStatus.universe_count
                      ? 'bg-terminal-green/5 border-terminal-green/30'
                      : tickerStatus.symbols_current > tickerStatus.universe_count * 0.9
                      ? 'bg-terminal-amber/5 border-terminal-amber/30'
                      : 'bg-terminal-red/5 border-terminal-red/30'
                  }`}>
                    <div className="text-[10px] text-white/60 uppercase tracking-wider">Current Symbols</div>
                    <div className={`text-2xl font-bold mt-1 ${
                      tickerStatus.symbols_current === tickerStatus.universe_count
                        ? 'text-terminal-green'
                        : tickerStatus.symbols_current > tickerStatus.universe_count * 0.9
                        ? 'text-terminal-amber'
                        : 'text-terminal-red'
                    }`}>
                      {tickerStatus.symbols_current.toLocaleString()}
                    </div>
                    <div className="text-[10px] text-white/50 mt-0.5">
                      of {tickerStatus.universe_count.toLocaleString()} universe
                    </div>
                  </div>

                  {/* Stale symbols */}
                  <div className={`p-3 rounded border ${
                    tickerStatus.symbols_stale === 0
                      ? 'bg-terminal-green/5 border-terminal-green/30'
                      : tickerStatus.symbols_stale < 50
                      ? 'bg-terminal-amber/5 border-terminal-amber/30'
                      : 'bg-terminal-red/5 border-terminal-red/30'
                  }`}>
                    <div className="text-[10px] text-white/60 uppercase tracking-wider">Stale Symbols</div>
                    <div className={`text-2xl font-bold mt-1 ${
                      tickerStatus.symbols_stale === 0
                        ? 'text-terminal-green'
                        : tickerStatus.symbols_stale < 50
                        ? 'text-terminal-amber'
                        : 'text-terminal-red'
                    }`}>
                      {tickerStatus.symbols_stale.toLocaleString()}
                    </div>
                    <div className="text-[10px] text-white/50 mt-0.5">behind last trading day</div>
                  </div>

                  {/* Last update */}
                  <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
                    <div className="text-[10px] text-white/60 uppercase tracking-wider">Last Update</div>
                    <div className="text-sm text-white font-bold mt-1">
                      {tickerStatus.last_update_time
                        ? new Date(tickerStatus.last_update_time).toLocaleString('en-IN', {
                            day: '2-digit',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: false,
                          })
                        : '—'}
                    </div>
                    <div className="text-[10px] text-white/50 mt-0.5">
                      {tickerStatus.total_rows.toLocaleString()} total rows
                    </div>
                  </div>
                </div>

                {/* Row 2: Freshness breakdown */}
                <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
                  <div className="text-[10px] text-white/60 uppercase tracking-wider mb-3">
                    Data Freshness Breakdown
                    <span className="ml-2 text-white/30 normal-case">(universe symbols)</span>
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { key: '0', label: 'Up to date', color: 'text-terminal-green', bar: 'bg-terminal-green' },
                      { key: '1', label: '1 day behind', color: 'text-terminal-amber', bar: 'bg-terminal-amber' },
                      { key: '2', label: '2 days behind', color: 'text-orange-400', bar: 'bg-orange-400' },
                      { key: '3+', label: '3+ days / no data', color: 'text-terminal-red', bar: 'bg-terminal-red' },
                    ].map(({ key, label, color, bar }) => {
                      const count = tickerStatus.days_behind_breakdown[key] ?? 0;
                      const pct = tickerStatus.universe_count > 0
                        ? (count / tickerStatus.universe_count) * 100
                        : 0;
                      return (
                        <div key={key} className="text-center">
                          <div className={`text-2xl font-bold ${color}`}>
                            {count.toLocaleString()}
                          </div>
                          <div className="text-[10px] text-white/50 mt-0.5">{label}</div>
                          <div className="mt-2 h-1.5 bg-terminal-gray/30 rounded overflow-hidden">
                            <div className={`h-full ${bar} transition-[width,background-color,color,transform]`} style={{ width: `${pct}%` }} />
                          </div>
                          <div className="text-[10px] text-white/30 mt-0.5">{pct.toFixed(1)}%</div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Row 3: Watchlist coverage */}
                <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
                  <div className="text-[10px] text-white/60 uppercase tracking-wider mb-2">
                    Watchlist Coverage
                  </div>
                  <div className="flex items-center gap-3 mb-1.5">
                    <div className="flex-1 h-2 bg-terminal-gray rounded overflow-hidden">
                      <div
                        className="h-full bg-terminal-green transition-[width,background-color,color,transform]"
                        style={{
                          width: `${tickerStatus.watchlist_symbols_total > 0
                            ? (tickerStatus.watchlist_symbols_current / tickerStatus.watchlist_symbols_total) * 100
                            : 0}%`,
                        }}
                      />
                    </div>
                    <span className="text-sm font-bold text-terminal-green w-20 text-right">
                      {tickerStatus.watchlist_symbols_current}/{tickerStatus.watchlist_symbols_total} current
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-1.5 bg-terminal-gray rounded overflow-hidden">
                      <div
                        className="h-full bg-blue-400 transition-[width,background-color,color,transform]"
                        style={{
                          width: `${tickerStatus.watchlist_symbols_total > 0
                            ? (tickerStatus.watchlist_symbols_covered / tickerStatus.watchlist_symbols_total) * 100
                            : 0}%`,
                        }}
                      />
                    </div>
                    <span className="text-xs font-bold text-blue-400 w-20 text-right">
                      {tickerStatus.watchlist_symbols_covered}/{tickerStatus.watchlist_symbols_total} covered
                    </span>
                  </div>
                  <div className="text-[10px] text-white/40 mt-1.5">
                    &quot;current&quot; = has data for the last trading day &nbsp;|&nbsp; &quot;covered&quot; = has any historical data
                  </div>
                </div>

                {/* Row 4: Intraday warehouse stats */}
                {tickerStatus.intraday_stats && (
                  <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
                    <div className="text-[10px] text-white/60 uppercase tracking-wider mb-3">
                      Intraday Data Warehouse
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      {([
                        { key: '1h', label: '1H Candles' },
                        { key: 'W', label: 'Weekly' },
                        { key: 'M', label: 'Monthly' },
                      ] as const).map(({ key, label }) => {
                        const stat = tickerStatus.intraday_stats[key];
                        if (!stat) return null;
                        const watchlistTotal = tickerStatus.watchlist_symbols_total;
                        const universeTotal = tickerStatus.universe_count;
                        const is1h = key === '1h';
                        const isUniverseInterval = key === 'W' || key === 'M';

                        const coveredPct = watchlistTotal > 0
                          ? (stat.watchlist_covered / watchlistTotal) * 100
                          : 0;
                        const indicatorsPct = stat.watchlist_covered > 0
                          ? (stat.symbols_with_indicators / stat.watchlist_covered) * 100
                          : 0;
                        const universeCoveredPct = universeTotal > 0
                          ? (stat.universe_covered / universeTotal) * 100
                          : 0;
                        const universeIndicatorsPct = stat.universe_covered > 0
                          ? (stat.universe_symbols_with_indicators / stat.universe_covered) * 100
                          : 0;
                        const currentPct = is1h && watchlistTotal > 0
                          ? (stat.watchlist_current / watchlistTotal) * 100
                          : 0;
                        const currentColor = is1h
                          ? stat.watchlist_current === watchlistTotal
                            ? 'text-terminal-green'
                            : stat.watchlist_current > 0
                            ? 'text-terminal-amber'
                            : 'text-terminal-red'
                          : '';
                        return (
                          <div key={key} className="bg-black/20 rounded p-3">
                            <div className="text-[10px] text-white/40 uppercase tracking-wider mb-2">
                              {label}
                            </div>
                            <div className="space-y-2">
                              <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/50">Rows</span>
                                <span className="text-sm font-bold text-white">
                                  {stat.total_rows.toLocaleString()}
                                </span>
                              </div>
                              {isUniverseInterval && (
                                <>
                                  <div className="flex justify-between items-center">
                                    <span className="text-[10px] text-white/50">Universe</span>
                                    <span className="text-xs font-bold text-terminal-green">
                                      {stat.universe_covered.toLocaleString()}/{universeTotal.toLocaleString()}
                                    </span>
                                  </div>
                                  <div className="h-1 bg-terminal-gray/30 rounded overflow-hidden">
                                    <div
                                      className="h-full bg-terminal-green transition-[width,background-color,color,transform]"
                                      style={{ width: `${universeCoveredPct}%` }}
                                    />
                                  </div>
                                  <div className="flex justify-between items-center">
                                    <span className="text-[10px] text-white/50">Univ. Indicators</span>
                                    <span className="text-xs font-bold text-terminal-green">
                                      {stat.universe_symbols_with_indicators.toLocaleString()}/{stat.universe_covered.toLocaleString()}
                                    </span>
                                  </div>
                                  <div className="h-1 bg-terminal-gray/30 rounded overflow-hidden">
                                    <div
                                      className="h-full bg-terminal-green/60 transition-[width,background-color,color,transform]"
                                      style={{ width: `${universeIndicatorsPct}%` }}
                                    />
                                  </div>
                                  <div className="border-t border-terminal-gray/20 pt-1" />
                                </>
                              )}
                              <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/50">Watchlist</span>
                                <span className="text-xs font-bold text-blue-400">
                                  {stat.watchlist_covered}/{watchlistTotal}
                                </span>
                              </div>
                              <div className="h-1 bg-terminal-gray/30 rounded overflow-hidden">
                                <div
                                  className="h-full bg-blue-400 transition-[width,background-color,color,transform]"
                                  style={{ width: `${coveredPct}%` }}
                                />
                              </div>
                              {is1h && (
                                <div className="flex justify-between items-center">
                                  <span className="text-[10px] text-white/50">Current</span>
                                  <span className={`text-xs font-bold ${currentColor}`}>
                                    {stat.watchlist_current}/{watchlistTotal}
                                  </span>
                                </div>
                              )}
                              <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/50">WL Indicators</span>
                                <span className="text-xs font-bold text-blue-400">
                                  {stat.symbols_with_indicators}/{stat.watchlist_covered}
                                </span>
                              </div>
                              <div className="h-1 bg-terminal-gray/30 rounded overflow-hidden">
                                <div
                                  className="h-full bg-blue-400/60 transition-[width,background-color,color,transform]"
                                  style={{ width: `${indicatorsPct}%` }}
                                />
                              </div>
                              <div className="flex justify-between items-center pt-1">
                                <span className="text-[10px] text-white/50">Latest</span>
                                <span className="text-[10px] text-white/70">
                                  {stat.latest_timestamp
                                    ? new Date(stat.latest_timestamp).toLocaleString('en-IN', {
                                        day: '2-digit',
                                        month: 'short',
                                        hour: '2-digit',
                                        minute: '2-digit',
                                        hour12: false,
                                      })
                                    : '—'}
                                </span>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Row 5: Backfill progress */}
                <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-[10px] text-white/60 uppercase tracking-wider">
                      Overall Freshness
                    </div>
                    <span className={`text-sm font-bold ${
                      tickerStatus.backfill_progress_percent === 100
                        ? 'text-terminal-green'
                        : tickerStatus.backfill_progress_percent >= 95
                        ? 'text-terminal-amber'
                        : 'text-terminal-red'
                    }`}>
                      {tickerStatus.backfill_progress_percent.toFixed(1)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-2 bg-terminal-gray rounded overflow-hidden">
                      <div
                        className={`h-full transition-[width,background-color,color,transform] ${
                          tickerStatus.backfill_progress_percent === 100
                            ? 'bg-terminal-green'
                            : tickerStatus.backfill_progress_percent >= 95
                            ? 'bg-terminal-amber'
                            : 'bg-terminal-red'
                        }`}
                        style={{ width: `${tickerStatus.backfill_progress_percent}%` }}
                      />
                    </div>
                  </div>
                  {tickerStatus.backfill_pending > 0 && (
                    <div className="text-[10px] text-white/60 mt-2">
                      {tickerStatus.backfill_pending} symbol{tickerStatus.backfill_pending !== 1 ? 's' : ''} pending update
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="flex gap-2 pt-2 flex-wrap">
                  <button
                    onClick={handleTriggerBackfill}
                    className="px-4 py-2 text-xs bg-terminal-amber/10 text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors"
                  >
                    Trigger Backfill
                  </button>
                  <button
                    onClick={handleTriggerDailyUpdate}
                    className="px-4 py-2 text-xs bg-terminal-amber/10 text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors"
                  >
                    Trigger Daily Update
                  </button>
                  <button
                    onClick={openLogs}
                    className="px-4 py-2 text-xs bg-white/5 text-white/70 hover:bg-white/10 hover:text-white transition-colors ml-auto"
                  >
                    Backend Logs <span className="text-[10px] text-terminal-amber/70 ml-1">[POP]</span>
                  </button>
                </div>

                {/* Symbol Health */}
                <div className="bg-terminal-gray/10 p-3 rounded border border-terminal-gray/20">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-[10px] text-white/60 uppercase tracking-wider">
                      Symbol Health
                    </div>
                    <div className="text-[10px] text-white/40">
                      {errorsLoading ? 'Loading...' : symbolErrors
                        ? Object.values(symbolErrors).reduce((s, c) => s + c.count, 0) + ' errored symbols'
                        : '—'}
                    </div>
                  </div>

                  {errorsLoading ? (
                    <div className="text-[10px] text-white/40 py-4 text-center">Loading...</div>
                  ) : symbolErrors ? (
                    <div className="space-y-3">
                      {([
                        { key: 'delisted', label: 'Delisted', color: 'text-terminal-red' },
                        { key: 'illiquid', label: 'Illiquid Series', color: 'text-orange-400' },
                        { key: 'suspended', label: 'Suspended', color: 'text-yellow-400' },
                        { key: 'not_tradable', label: 'Not Tradable', color: 'text-terminal-amber' },
                        { key: 'unknown', label: 'Unknown Error', color: 'text-white/60' },
                      ] as const).map(({ key, label, color }) => {
                        const cat = symbolErrors[key];
                        if (!cat || cat.count === 0) return null;
                        return (
                          <div key={key}>
                            <div className={`text-[10px] uppercase tracking-wider mb-1 ${color}`}>
                              {label} ({cat.count})
                            </div>
                            <div className="space-y-1">
                              {cat.symbols.map((s) => (
                                <div
                                  key={s.symbol}
                                  className="flex items-center gap-2 py-1 px-2 bg-black/20 rounded text-[10px]"
                                >
                                  <div className="flex-1 min-w-0">
                                    <div className="font-bold text-white truncate">{s.symbol}</div>
                                    <div className="text-white/40 truncate">{s.companyName || '—'}</div>
                                  </div>
                                  {s.series && (
                                    <div className="px-1.5 py-0.5 bg-white/10 rounded text-[9px] text-white/60">
                                      {s.series}
                                    </div>
                                  )}
                                  <div className="flex items-center gap-1 ml-auto shrink-0">
                                    <input
                                      type="text"
                                      placeholder="New symbol"
                                      value={changingSymbol === s.symbol ? changeSymbolInput : ''}
                                      onChange={(e) => {
                                        setChangingSymbol(s.symbol);
                                        setChangeSymbolInput(e.target.value.toUpperCase());
                                      }}
                                      className="w-20 px-1 py-0.5 bg-terminal-bg border border-terminal-gray rounded text-[10px] text-white placeholder-white/30 focus:border-terminal-amber focus:outline-none"
                                    />
                                    <button
                                      onClick={() => handleChangeSymbol(s.symbol)}
                                      disabled={changingSymbol === s.symbol}
                                      className="px-1.5 py-0.5 bg-blue-500/20 text-blue-400 hover:bg-blue-500/40 text-[9px] font-bold disabled:opacity-30 transition-colors"
                                    >
                                      CHANGE
                                    </button>
                                    <button
                                      onClick={() => handleRemoveSymbol(s.symbol)}
                                      className="px-1.5 py-0.5 bg-terminal-red/20 text-terminal-red hover:bg-terminal-red/40 text-[9px] font-bold transition-colors"
                                    >
                                      REMOVE
                                    </button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                      {Object.values(symbolErrors).every(c => c.count === 0) && (
                        <div className="text-[10px] text-terminal-green py-2 text-center">
                          All symbols are healthy
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-[10px] text-white/40 py-4 text-center">Failed to load</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-white/60">No data available</div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="mt-6 pt-4 border-t border-terminal-gray text-[10px] text-white/50">
          <p>Jobs are automatically synced from the background task registry on server startup.</p>
          <p className="mt-1">Use the RUN button to manually trigger a job. Use ENABLE/DISABLE to control scheduled runs.</p>
        </div>
      </div>
    </div>
  );
}


