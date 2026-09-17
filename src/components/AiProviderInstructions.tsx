'use client';

import { AI_PROVIDER_MAP } from '@/lib/aiProviders';

interface Props {
  providerId: string;
}

/**
 * Step-by-step setup instructions for the selected AI provider.
 * Shared by SettingsWidget and FirstLaunchModal (both use terminal-* classes).
 */
export function AiProviderInstructions({ providerId }: Props) {
  const meta = AI_PROVIDER_MAP[providerId];
  if (!meta) return null;
  const hasBody =
    meta.requiresSubscription ||
    meta.requiresApp ||
    meta.steps.length > 0 ||
    meta.links.length > 0;
  if (!hasBody) return null;

  return (
    <div className="flex flex-col gap-1 mt-1 border border-terminal-border/60 p-2 bg-terminal-bg/50">
      <span className="text-terminal-amber/90 text-[10px] font-bold uppercase tracking-widest">
        Setup — {meta.label}
      </span>
      {meta.requiresSubscription && (
        <span className="text-white/70 text-[10px]">{meta.requiresSubscription}</span>
      )}
      {meta.requiresApp && (
        <span className="text-white/70 text-[10px]">{meta.requiresApp}</span>
      )}
      {meta.steps.length > 0 && (
        <ol className="flex flex-col gap-0.5 text-white/70 text-[10px] list-decimal list-inside">
          {meta.steps.map((s, i) => (
            <li key={i} className="leading-relaxed">
              {s}
            </li>
          ))}
        </ol>
      )}
      {meta.links.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          {meta.links.map((l) => (
            <a
              key={l.url}
              href={l.url}
              target="_blank"
              rel="noreferrer"
              className="text-terminal-amber text-[10px] underline break-all"
            >
              {l.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
