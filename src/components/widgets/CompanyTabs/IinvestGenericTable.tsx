'use client';

import React from 'react';

export interface IinvestColumn {
  field: string;
  displayName: string;
  dataType?: string;
  format?: string;
}

function formatCell(
  value: unknown,
  dataType: string | undefined,
  format: string | undefined,
): string {
  if (value === null || value === undefined || value === '') return '—';
  if (
    dataType === 'String' ||
    dataType === 'Date' ||
    format === 'd-mmm-yy' ||
    format?.startsWith('d-')
  ) {
    return String(value);
  }
  if (dataType === 'Number' || typeof value === 'number') {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return String(value);
    return n.toLocaleString('en-IN');
  }
  return String(value);
}

export function IinvestGenericTable({
  data,
  columns,
  emptyMsg,
}: {
  data: unknown;
  columns: IinvestColumn[];
  emptyMsg: string;
}) {
  if (!Array.isArray(data) || data.length === 0) {
    return <div className="text-zinc-300 text-sm py-2 px-1">{emptyMsg}</div>;
  }
  const rows = data as Array<Record<string, unknown>>;
  const visibleCols = columns.filter((c) => c.field !== 'f_25008');

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="text-xs text-zinc-300 uppercase">
          {visibleCols.map((c) => (
            <th key={c.field} className="text-left pb-1 pr-2 font-normal whitespace-nowrap">
              {c.displayName}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 50).map((row, i) => (
          <tr key={i} className="border-b border-terminal-gray/40">
            {visibleCols.map((c) => (
              <td
                key={c.field}
                className="py-[2px] pr-2 text-white text-sm font-mono whitespace-nowrap"
              >
                {formatCell(row[c.field], c.dataType, c.format)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
