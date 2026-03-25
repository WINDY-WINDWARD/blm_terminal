'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';

interface Job {
  job_key: string;
  name: string;
  description: string | null;
  category: string | null;
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

  return (
    <div className="min-h-screen bg-terminal-bg text-white font-mono p-4">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 border-b border-terminal-gray pb-2">
          <div>
            <h1 className="text-2xl text-terminal-amber font-bold">JOBS</h1>
            <p className="text-xs text-white/60">Background task management</p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/"
              className="px-3 py-1 text-xs border border-terminal-gray text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors"
            >
              ← BACK
            </Link>
            <button
              onClick={fetchJobs}
              className="px-3 py-1 text-xs border border-terminal-gray text-terminal-amber hover:bg-terminal-amber hover:text-terminal-bg transition-colors"
            >
              REFRESH
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-terminal-red/10 border border-terminal-red text-terminal-red text-xs">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-terminal-amber">Loading...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-terminal-gray text-terminal-amber uppercase text-[10px] tracking-widest">
                  <th className="text-left py-2 px-2">Job</th>
                  <th className="text-left py-2 px-2">Category</th>
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
                    <td className="py-2 px-2">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="py-2 px-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 bg-terminal-gray rounded overflow-hidden">
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
                    <td className="py-2 px-2 text-white/70">{formatDate(job.next_trigger_at)}</td>
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
