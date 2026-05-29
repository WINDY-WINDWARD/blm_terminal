'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';

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

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<'jobs' | 'stats'>('jobs');
  const [tickerStatus, setTickerStatus] = useState<TickerStatus | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [symbolErrors, setSymbolErrors] = useState<SymbolErrors | null>(null);
  const [errorsLoading, setErrorsLoading] = useState(false);
  const [changeSymbolInput, setChangeSymbolInput] = useState<string>('');
  const [changingSymbol, setChangingSymbol] = useState<string | null>(null);

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

  return (
    <div className="h-screen overflow-y-auto bg-terminal-bg text-white font-mono p-4">
      <div className="w-full">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 border-b border-terminal-gray pb-2">
          <div>
            <h1 className="text-2xl text-terminal-amber font-bold">JOBS</h1>
            <p className="text-xs text-white/60">
              {activeTab === 'jobs' ? 'Background task management' : 'Ticker warehouse statistics'}
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
              onClick={activeTab === 'stats' ? fetchStats : fetchJobs}
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
                              className={`h-full transition-all ${
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
                            className="px-2 py-1 text-[10px] bg-terminal-amber/10 text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                          >
                            {triggering === job.job_key ? '...' : 'RUN'}
                          </button>
                          <button
                            onClick={() => handleToggle(job.job_key, !job.is_enabled)}
                            className={`px-2 py-1 text-[10px] transition-colors ${
                              job.is_enabled
                                ? 'bg-terminal-red/10 text-terminal-red hover:bg-terminal-red hover:text-white'
                                : 'bg-terminal-green/10 text-terminal-green hover:bg-terminal-green hover:text-terminal-bg'
                            }`}
                          >
                            {job.is_enabled ? 'DISABLE' : 'ENABLE'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
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
                            <div className={`h-full ${bar} transition-all`} style={{ width: `${pct}%` }} />
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
                        className="h-full bg-terminal-green transition-all"
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
                        className="h-full bg-blue-400 transition-all"
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
                                      className="h-full bg-terminal-green transition-all"
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
                                      className="h-full bg-terminal-green/60 transition-all"
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
                                  className="h-full bg-blue-400 transition-all"
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
                                  className="h-full bg-blue-400/60 transition-all"
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
                        className={`h-full transition-all ${
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
                <div className="flex gap-2 pt-2">
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
