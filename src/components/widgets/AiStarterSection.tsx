'use client';

import React from 'react';

export interface AiStarterSectionProps {
  label: string;
  count?: number;
  action?: React.ReactNode;
  children: React.ReactNode;
}

export function AiStarterSection({
  label,
  count,
  action,
  children,
}: AiStarterSectionProps) {
  return (
    <section className="w-full flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-zinc-400">
          {label}
        </span>
        {count !== undefined && (
          <span className="text-[10px] font-mono text-zinc-600">
            {count}
          </span>
        )}
        <div className="flex-1 h-px bg-[#27272a]" />
        {action}
      </div>
      <div className="grid grid-cols-1 @md:grid-cols-2 gap-2.5">
        {children}
      </div>
    </section>
  );
}
