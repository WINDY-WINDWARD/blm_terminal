'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchIinvestHealth,
  fetchIinvestAnnouncements,
  fetchIinvestBoardMeetings,
  fetchIinvestCorporateActions,
  fetchIinvestLegalCases,
  fetchIinvestCapitalHistory,
  type IinvestHealth,
  type IinvestAnnouncementRow,
} from '@/lib/iinvest';

interface IinvestSectionProps {
  label: string;
  defaultOpen?: boolean;
  count?: number | null;
  error?: string | null;
  children: React.ReactNode;
}

function IinvestSection({
  label,
  defaultOpen = false,
  count,
  error,
  children,
}: IinvestSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <details
      open={isOpen}
      onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
      className="border border-[#27272a] rounded bg-[#09090b] transition-colors duration-200"
    >
      <summary className="px-3 py-2 cursor-pointer list-none flex items-center gap-2 hover:bg-zinc-900/80 transition-colors select-none">
        <span className="text-terminal-amber text-xs font-mono w-4">
          {isOpen ? '▼' : '▶'}
        </span>
        <span className="text-xs text-white/90 font-mono font-semibold uppercase tracking-wider">
          {label}
        </span>
        {count != null && count > 0 && (
          <span className="text-xs px-1.5 py-0.2 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber font-mono font-bold">
            {count}
          </span>
        )}
        {error && (
          <span className="text-xs text-terminal-red font-mono ml-auto">
            unavailable
          </span>
        )}
      </summary>
      <div className="px-3 py-2.5 border-t border-[#27272a]/60 bg-black/40">
        {error ? (
          <div className="text-white/60 text-xs font-mono py-1">
            {error}
          </div>
        ) : (
          children
        )}
      </div>
    </details>
  );
}

function FormattedRowList({
  rows,
  type,
}: {
  rows?: unknown[];
  type: 'corporateActions' | 'boardMeetings' | 'capitalHistory' | 'legalCases';
}) {
  if (!rows || rows.length === 0) {
    return <div className="text-white/40 text-xs font-mono py-2">No records found.</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse font-mono text-xs">
        <tbody>
          {rows.slice(0, 20).map((r, i) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const row = r as Record<string, any>;
            if (type === 'corporateActions') {
              const dateStr = row.f_81 || row.xEx_Date;
              const date = dateStr && typeof dateStr === 'string' ? dateStr.substring(0, 10) : '—';
              return (
                <tr key={i} className="border-b border-[#27272a]/40 hover:bg-white/[0.02]">
                  <td className="py-1.5 pr-3 text-zinc-400 whitespace-nowrap">{date}</td>
                  <td className="py-1.5 text-white/90 font-medium">{row.f_79 || '—'}</td>
                </tr>
              );
            }
            if (type === 'boardMeetings') {
              const dateStr = row.f_43 || row.xMeeting_Date;
              const date = dateStr && typeof dateStr === 'string' ? dateStr.substring(0, 10) : '—';
              const link = typeof row.f_44 === 'string' ? row.f_44 : undefined;
              const text = row.f_41 || '—';
              return (
                <tr key={i} className="border-b border-[#27272a]/40 hover:bg-white/[0.02]">
                  <td className="py-1.5 pr-3 text-zinc-400 whitespace-nowrap">{date}</td>
                  <td className="py-1.5 text-white/90">
                    {link ? (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-terminal-amber hover:underline hover:text-terminal-amber/80"
                      >
                        {text}
                      </a>
                    ) : (
                      text
                    )}
                  </td>
                </tr>
              );
            }
            if (type === 'capitalHistory') {
              return (
                <tr key={i} className="border-b border-[#27272a]/40 hover:bg-white/[0.02]">
                  <td className="py-1.5 pr-3 text-zinc-400 whitespace-nowrap">{row.f_139 || '—'}</td>
                  <td className="py-1.5 pr-3 text-white/90">{row.f_140 || '—'}</td>
                  <td className="py-1.5 text-terminal-amber text-right font-semibold">{row.f_141 || '—'}</td>
                </tr>
              );
            }
            if (type === 'legalCases') {
              const dateStr = typeof row.f_165 === 'string' ? row.f_165.substring(0, 10) : '—';
              let title = typeof row.f_163 === 'string' ? row.f_163 : '';
              title = title.replace(/<[^>]*>?/gm, '');
              const source = typeof row.f_164 === 'string' ? row.f_164 : '';

              return (
                <tr key={i} className="border-b border-[#27272a]/40 hover:bg-white/[0.02]">
                  <td className="py-2 pr-3 text-white/90 whitespace-normal">
                    <div className="font-medium text-white">{title || '—'}</div>
                    <div className="text-[11px] text-zinc-500 mt-0.5">{dateStr} • {source}</div>
                  </td>
                </tr>
              );
            }
            return null;
          })}
        </tbody>
      </table>
    </div>
  );
}

export function CorporateTab({ symbol }: { symbol: string }) {
  const { data: iinvestHealth, isLoading: isHealthLoading } = useQuery<IinvestHealth>({
    queryKey: ['iinvest', 'health'],
    queryFn: () => fetchIinvestHealth(),
    staleTime: 60_000,
    retry: false,
  });
  const iinvestAvailable = iinvestHealth?.healthy === true;

  const { data: nseRatios } = useQuery<{
    symbol_pe: number | null;
    sector_pe: number | null;
    high_52w: number | null;
    low_52w: number | null;
  }>({
    queryKey: ['nse', 'ratios', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/stockuniverse/${encodeURIComponent(symbol)}/ratios`);
      if (!res.ok) return null;
      return res.json();
    },
    enabled: !!symbol,
    staleTime: 15 * 60 * 1000,
    retry: false,
  });

  const { data: announcements, isLoading: isAnncLoading } = useQuery<{
    response: { data?: IinvestAnnouncementRow[] };
  }>({
    queryKey: ['iinvest', 'announcements', symbol],
    queryFn: () => fetchIinvestAnnouncements(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 15 * 60 * 1000,
    retry: false,
  });

  const { data: boardMeetings } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'board-meetings', symbol],
    queryFn: () => fetchIinvestBoardMeetings(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  const { data: corporateActions } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'corporate-actions', symbol, 'Dividend'],
    queryFn: () => fetchIinvestCorporateActions(symbol, 'Dividend'),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  const { data: legalCases } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'legal-cases', symbol],
    queryFn: () => fetchIinvestLegalCases(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  const { data: capitalHistory } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'capital-history', symbol],
    queryFn: () => fetchIinvestCapitalHistory(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-y-auto bg-black p-3 space-y-2.5">
      {/* Header Info */}
      <div className="flex items-center justify-between border border-[#27272a] rounded bg-[#09090b] px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-terminal-amber font-bold text-sm tracking-wide">{symbol}</span>
          <span className="text-zinc-500">CORPORATE & REGULATORY DISCLOSURES</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wider">iInvest Integration:</span>
          {isHealthLoading ? (
            <span className="text-zinc-500 text-xs">Checking...</span>
          ) : iinvestAvailable ? (
            <span className="text-terminal-green text-xs font-semibold flex items-center gap-1">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-terminal-green animate-pulse"></span>
              ONLINE
            </span>
          ) : (
            <span className="text-zinc-500 text-xs">OFFLINE (REDUCED MODE)</span>
          )}
        </div>
      </div>

      {/* Accordions */}
      <div className="space-y-2">
        {/* NSE Market Ratios */}
        <IinvestSection
          label="NSE Market Snapshot"
          defaultOpen={true}
        >
          {nseRatios ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 py-1">
              <div className="bg-black/50 border border-[#27272a]/60 rounded p-2">
                <div className="text-[10px] uppercase text-zinc-500">P/E Ratio</div>
                <div className="text-sm font-bold text-terminal-amber mt-0.5">
                  {nseRatios.symbol_pe != null ? nseRatios.symbol_pe.toFixed(2) : '—'}
                </div>
              </div>
              <div className="bg-black/50 border border-[#27272a]/60 rounded p-2">
                <div className="text-[10px] uppercase text-zinc-500">Sector P/E</div>
                <div className="text-sm font-bold text-white mt-0.5">
                  {nseRatios.sector_pe != null ? nseRatios.sector_pe.toFixed(2) : '—'}
                </div>
              </div>
              <div className="bg-black/50 border border-[#27272a]/60 rounded p-2">
                <div className="text-[10px] uppercase text-zinc-500">52W High</div>
                <div className="text-sm font-bold text-terminal-green mt-0.5">
                  {nseRatios.high_52w != null ? `₹${nseRatios.high_52w.toFixed(2)}` : '—'}
                </div>
              </div>
              <div className="bg-black/50 border border-[#27272a]/60 rounded p-2">
                <div className="text-[10px] uppercase text-zinc-500">52W Low</div>
                <div className="text-sm font-bold text-terminal-red mt-0.5">
                  {nseRatios.low_52w != null ? `₹${nseRatios.low_52w.toFixed(2)}` : '—'}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-zinc-500 text-xs py-1">NSE ratio data unavailable</div>
          )}
        </IinvestSection>

        {/* Announcements */}
        <IinvestSection
          label="Corporate Announcements"
          count={announcements?.response?.data?.length}
          defaultOpen={true}
        >
          {isAnncLoading ? (
            <div className="text-zinc-500 text-xs py-2">Loading announcements...</div>
          ) : announcements?.response?.data && announcements.response.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse font-mono text-xs">
                <thead>
                  <tr className="border-b border-[#27272a] text-zinc-500 text-[10px] uppercase text-left">
                    <th className="py-1 pr-3 font-normal">Date</th>
                    <th className="py-1 font-normal">Subject</th>
                  </tr>
                </thead>
                <tbody>
                  {announcements.response.data.slice(0, 15).map((a, i) => {
                    const dateStr =
                      typeof a.f_156 === 'string'
                        ? a.f_156.substring(0, 10)
                        : typeof a.xEx_Date === 'string'
                        ? a.xEx_Date.substring(0, 10)
                        : '—';
                    const text = a.f_158 || a.xPurpose || '—';
                    const link = typeof a.f_159 === 'string' ? a.f_159 : undefined;
                    return (
                      <tr key={i} className="border-b border-[#27272a]/40 hover:bg-white/[0.02]">
                        <td className="py-1.5 pr-3 text-zinc-400 whitespace-nowrap align-top">{dateStr}</td>
                        <td className="py-1.5 text-white/90">
                          {link ? (
                            <a
                              href={link}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-white hover:text-terminal-amber hover:underline"
                            >
                              {text}
                            </a>
                          ) : (
                            text
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-zinc-500 text-xs py-2">No corporate announcements on record.</div>
          )}
        </IinvestSection>

        {/* Corporate Actions */}
        <IinvestSection
          label="Corporate Actions & Dividends"
          count={corporateActions?.response?.data?.length}
        >
          <FormattedRowList rows={corporateActions?.response?.data} type="corporateActions" />
        </IinvestSection>

        {/* Board Meetings */}
        <IinvestSection
          label="Board Meetings"
          count={boardMeetings?.response?.data?.length}
        >
          <FormattedRowList rows={boardMeetings?.response?.data} type="boardMeetings" />
        </IinvestSection>

        {/* Legal Cases */}
        <IinvestSection
          label="Litigation & Legal Cases"
          count={legalCases?.response?.data?.length}
        >
          <FormattedRowList rows={legalCases?.response?.data} type="legalCases" />
        </IinvestSection>

        {/* Capital History */}
        <IinvestSection
          label="Capital Structure History"
          count={capitalHistory?.response?.data?.length}
        >
          <FormattedRowList rows={capitalHistory?.response?.data} type="capitalHistory" />
        </IinvestSection>
      </div>
    </div>
  );
}
