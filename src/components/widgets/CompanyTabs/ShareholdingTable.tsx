"use client";

import React, { useState, useEffect } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

export interface ScreenerCompanyData {
  shareholding?: Array<{
    period: string;
    promoters: number | null;
    fiis: number | null;
    diis: number | null;
    public: number | null;
    government: number | null;
  }>;
}

export type ShareholdingCellValue = { per?: number; val?: number } | null | undefined;

export function ShareholdingTable({
  data,
  screenerData,
}: {
  data: unknown;
  screenerData?: ScreenerCompanyData;
}) {
  if (!Array.isArray(data) || data.length === 0) {
    return <div className="text-zinc-300 text-sm py-2 px-1">No records</div>;
  }

  const headerRow = data[0];
  if (!Array.isArray(headerRow)) {
    return <div className="text-zinc-300 text-sm py-2 px-1">No records</div>;
  }
  const headers = headerRow as string[];
  const descIdx = headers.indexOf("Description");
  const idIdx = headers.indexOf("ID");
  const isExpandedIdx = headers.indexOf("IsExpanded");
  if (descIdx < 0 || idIdx < 0 || isExpandedIdx < 0) {
    return <div className="text-zinc-300 text-sm py-2 px-1">Invalid shape</div>;
  }
  const quarterIdxs = headers
    .map((h, i) => ({ h, i }))
    .filter(({ h }) => /^(Mar|Jun|Sep|Dec)-\d{2}$/.test(h))
    .slice(0, 4);
  const quarterLabels = quarterIdxs.map((q) => q.h);

  const dataRows = data.slice(1) as unknown[][];

  const groups = dataRows.filter(
    (r) => r[isExpandedIdx] === true && (r[idIdx + 1] === null || r[idIdx + 1] === undefined),
  );
  const childrenByParent: Record<string, unknown[][]> = {};
  for (const r of dataRows) {
    if (r[isExpandedIdx] === true) continue;
    const parentId = r[idIdx + 1];
    if (parentId === null || parentId === undefined) continue;
    const key = String(parentId);
    if (!childrenByParent[key]) childrenByParent[key] = [];
    childrenByParent[key].push(r);
  }

  // Precompute aggregate totals for each group across all quarters
  const aggregatesByGroup: Record<string, Record<number, { per: number; val: number }>> = {};
  for (const group of groups) {
    const groupId = String(group[idIdx]);
    const children = childrenByParent[groupId] ?? [];
    aggregatesByGroup[groupId] = {};
    for (const { i: colIdx } of quarterIdxs) {
      let perSum = 0;
      let valSum = 0;
      let hasData = false;
      for (const row of children) {
        const cell = row[colIdx] as ShareholdingCellValue;
        if (cell && cell.per != null) {
          perSum += cell.per;
          if (cell.val != null) valSum += cell.val;
          hasData = true;
        }
      }
      if (hasData) {
        aggregatesByGroup[groupId][colIdx] = { per: perSum, val: valSum };
      }
    }
  }

  // All groups start collapsed by default
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(groups.map((g) => String(g[idIdx]))),
  );

  const groupIdsKey = groups.map((g) => String(g[idIdx])).join(",");
  useEffect(() => {
    setCollapsedGroups(new Set(groups.map((g) => String(g[idIdx]))));
  }, [groupIdsKey]);

  const toggleGroup = (id: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const latestQ = quarterIdxs[0];

  let pieData: Array<{ name: string; value: number }> = [];
  let fiiQoQ: number | null = null;
  let diiQoQ: number | null = null;
  let latestPeriod = quarterLabels[0] ?? "Latest";
  let prevPeriod = quarterLabels[1] ?? "Previous";

  if (screenerData?.shareholding && screenerData.shareholding.length >= 2) {
    const sh = screenerData.shareholding;
    const latest = sh[sh.length - 1];
    const prev = sh[sh.length - 2];
    latestPeriod = latest.period;
    prevPeriod = prev.period;
    if (latest.promoters) pieData.push({ name: "Promoters", value: latest.promoters });
    if (latest.fiis) pieData.push({ name: "FIIs", value: latest.fiis });
    if (latest.diis) pieData.push({ name: "DIIs", value: latest.diis });
    if (latest.public) pieData.push({ name: "Public", value: latest.public });
    if (latest.government) pieData.push({ name: "Govt", value: latest.government });
    pieData = pieData.sort((a, b) => b.value - a.value);
    if (latest.fiis !== null && prev.fiis !== null) fiiQoQ = latest.fiis - prev.fiis;
    if (latest.diis !== null && prev.diis !== null) diiQoQ = latest.diis - prev.diis;
  } else {
    pieData = groups
      .map((group) => {
        const groupId = String(group[idIdx]);
        const groupDesc = (group[descIdx] as string) ?? `Group ${groupId}`;
        const children = childrenByParent[groupId] ?? [];
        let perSumLatest = 0;
        for (const row of children) {
          if (latestQ) {
            const cell = row[latestQ.i] as ShareholdingCellValue;
            if (cell && cell.per != null) perSumLatest += cell.per;
          }
        }
        return {
          name: groupDesc.length > 20 ? groupDesc.substring(0, 20) + "..." : groupDesc,
          value: Number(perSumLatest.toFixed(2)),
        };
      })
      .filter((d) => d.value > 0)
      .sort((a, b) => b.value - a.value);
  }

  const COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"];

  return (
    <div className="flex flex-col h-full w-full">
      {pieData.length > 0 && (
        <div className="flex flex-row items-center justify-between p-2 mb-3 bg-zinc-900/50 rounded flex-shrink-0">
          <div className="flex flex-col items-center flex-1 h-[140px] min-w-0">
            <span className="text-white font-bold text-sm uppercase mb-1">
              Holdings ({latestPeriod})
            </span>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={25} outerRadius={45} stroke="none">
                  {pieData.map((e, i) => (
                    <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <RechartsTooltip
                  contentStyle={{ backgroundColor: "#18181b", border: "1px solid #3f3f46", fontSize: "10px" }}
                  itemStyle={{ color: "#fff" }}
                  formatter={(val: unknown) => [`${Number(val).toFixed(2)}%`, undefined]}
                />
                <Legend
                  wrapperStyle={{ fontSize: "9px" }}
                  layout="vertical"
                  verticalAlign="middle"
                  align="right"
                  formatter={(value, entry: { payload?: { value?: number } }) =>
                    `${value} (${Number(entry.payload?.value ?? 0).toFixed(2)}%)`
                  }
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-col flex-1 items-center justify-center gap-2 min-w-0">
            <span className="text-zinc-300 text-sm uppercase font-bold text-center">
              QoQ Change ({prevPeriod} to {latestPeriod})
            </span>
            <div className="flex flex-col gap-1">
              {fiiQoQ !== null && (
                <div className="flex gap-2 items-center text-[11px]">
                  <span className="text-zinc-200 w-8">FII:</span>
                  {(fiiQoQ as number) > 0.005 ? (
                    <span className="text-terminal-green font-bold">▲ +{(fiiQoQ as number).toFixed(2)}%</span>
                  ) : (fiiQoQ as number) < -0.005 ? (
                    <span className="text-terminal-red font-bold">▼ {(fiiQoQ as number).toFixed(2)}%</span>
                  ) : (
                    <span className="text-zinc-200">0.00%</span>
                  )}
                </div>
              )}
              {diiQoQ !== null && (
                <div className="flex gap-2 items-center text-[11px]">
                  <span className="text-zinc-200 w-8">DII:</span>
                  {(diiQoQ as number) > 0.005 ? (
                    <span className="text-terminal-green font-bold">▲ +{(diiQoQ as number).toFixed(2)}%</span>
                  ) : (diiQoQ as number) < -0.005 ? (
                    <span className="text-terminal-red font-bold">▼ {(diiQoQ as number).toFixed(2)}%</span>
                  ) : (
                    <span className="text-zinc-200">0.00%</span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full border-collapse text-xs font-mono">
          <thead className="sticky top-0 z-10">
            <tr className="bg-[#09090b] border-b border-[#27272a]">
              <th className="text-left py-2 pl-3 text-[10px] text-zinc-400 uppercase tracking-wider font-semibold w-full">
                Description
              </th>
              {quarterLabels.map((q) => (
                <th key={q} className="text-right py-2 pr-3 text-xs whitespace-nowrap font-semibold">
                  <div className="leading-tight">
                    <div className="text-zinc-200">{q}</div>
                    <div className="text-zinc-500 text-[8px] uppercase tracking-wider">% · Shares</div>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const groupId = String(group[idIdx]);
              const groupDesc = (group[descIdx] as string) ?? `Group ${groupId}`;
              const isCollapsed = collapsedGroups.has(groupId);
              const children = childrenByParent[groupId] ?? [];
              const groupAggregates = aggregatesByGroup[groupId] ?? {};
              return (
                <ShareholdingGroupFragment
                  key={groupId}
                  groupId={groupId}
                  groupDesc={groupDesc}
                  groupRow={group}
                  aggregates={groupAggregates}
                  isCollapsed={isCollapsed}
                  onToggle={() => toggleGroup(groupId)}
                  descIdx={descIdx}
                  quarterIdxs={quarterIdxs}
                >
                  {children}
                </ShareholdingGroupFragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface ShareholdingGroupFragmentProps {
  groupId: string;
  groupDesc: string;
  groupRow: unknown[];
  aggregates: Record<number, { per: number; val: number }>;
  isCollapsed: boolean;
  onToggle: () => void;
  descIdx: number;
  quarterIdxs: { h: string; i: number }[];
  children: unknown[][];
}

export function ShareholdingGroupFragment({
  groupId,
  groupDesc,
  groupRow,
  aggregates,
  isCollapsed,
  onToggle,
  descIdx,
  quarterIdxs,
  children,
}: ShareholdingGroupFragmentProps) {
  const visibleChildren = isCollapsed
    ? []
    : children.filter((row) =>
        quarterIdxs.some(({ i: colIdx }) => {
          const cell = row[colIdx] as ShareholdingCellValue;
          return cell && cell.per != null;
        }),
      );

  return (
    <>
      {/* ── Group header row ────────────────────────────────────── */}
      <tr
        className={`cursor-pointer select-none transition-colors duration-150 ${
          isCollapsed
            ? "bg-[#121216] hover:bg-[#18181f] border-b border-[#27272a]"
            : "bg-[#181822] hover:bg-[#1e1e2c] border-b border-[#2e2e3a]"
        }`}
        onClick={onToggle}
        data-testid={`shareholding-group-${groupId}`}
      >
        <td
          className={`py-2 pl-3 pr-2 whitespace-nowrap transition-all duration-150 border-l-2 ${
            isCollapsed
              ? "border-l-transparent"
              : "border-l-terminal-amber"
          }`}
        >
          <div className="flex items-center gap-2">
            <span
              className={`text-[9px] transition-transform duration-200 inline-block ${
                isCollapsed ? "text-zinc-500" : "text-terminal-amber"
              }`}
              style={{ transform: isCollapsed ? "rotate(0deg)" : "rotate(90deg)" }}
            >
              ▶
            </span>
            <span
              className={`font-bold text-xs uppercase tracking-wide transition-colors duration-150 ${
                isCollapsed ? "text-zinc-100" : "text-terminal-amber"
              }`}
            >
              {groupDesc}
            </span>
          </div>
        </td>

        {/* Always show group aggregate totals whether collapsed or expanded */}
        {quarterIdxs.map(({ h, i: colIdx }) => {
          const cell = groupRow[colIdx] as ShareholdingCellValue;
          const agg = aggregates[colIdx];
          const per = cell && cell.per != null ? cell.per : agg?.per;
          const val = cell && cell.val != null ? cell.val : agg?.val;

          return (
            <td key={h} className="py-2 pr-3 text-right whitespace-nowrap">
              {per != null ? (
                <div className="leading-tight">
                  <div className="text-terminal-amber font-bold text-xs">
                    {per.toFixed(2)}
                  </div>
                  {val != null && (
                    <div className="text-zinc-400 text-[9px] font-mono">
                      {val.toLocaleString("en-IN")}
                    </div>
                  )}
                </div>
              ) : (
                <span className="text-zinc-600 text-xs">—</span>
              )}
            </td>
          );
        })}
      </tr>

      {/* ── Child rows (fade in, clean compact font, indented) ── */}
      {!isCollapsed &&
        visibleChildren.map((row, i) => {
          const desc = (row[descIdx] as string | null) ?? `Row ${i + 1}`;
          return (
            <tr
              key={`${groupId}-${i}`}
              className="border-b border-[#1c1c22]/50 hover:bg-white/[0.03] transition-colors duration-100 animate-in fade-in slide-in-from-top-1 duration-200"
              data-testid={`shareholding-row-${groupId}-${i}`}
            >
              <td className="py-1.5 pl-8 pr-2 text-[11px] text-zinc-300 whitespace-nowrap font-mono">
                {desc}
              </td>
              {quarterIdxs.map(({ h, i: colIdx }) => {
                const cell = row[colIdx] as ShareholdingCellValue;
                return (
                  <td key={h} className="py-1.5 pr-3 text-right whitespace-nowrap">
                    {cell && cell.per != null ? (
                      <div className="leading-tight">
                        <div className="text-zinc-200 text-[11px] font-semibold font-mono">
                          {cell.per.toFixed(2)}
                        </div>
                        {cell.val != null && (
                          <div className="text-zinc-500 text-[9px] font-mono">
                            {cell.val.toLocaleString("en-IN")}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-zinc-700 text-[11px]">—</span>
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
    </>
  );
}
