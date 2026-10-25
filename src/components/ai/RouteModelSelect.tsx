'use client';

import { useId } from 'react';
import type { RouteModelCatalogEntry } from '@/types/aiRoutes';

interface RouteModelSelectProps {
  label: string;
  value: string;
  routes: RouteModelCatalogEntry[];
  helperText: string;
  onChange: (modelId: string) => void;
  isLoading?: boolean;
  loadError?: boolean;
  onRetry?: () => void;
  disabled?: boolean;
}

const EMPTY_CATALOG_LABEL = 'No models available - open provider manager';

export function RouteModelSelect({
  label,
  value,
  routes,
  helperText,
  onChange,
  isLoading = false,
  loadError = false,
  onRetry,
  disabled = false,
}: RouteModelSelectProps) {
  const generatedId = useId();
  const selectId = `route-model-select-${generatedId}`;
  const helperId = `${selectId}-helper`;
  const errorId = `${selectId}-error`;
  const routesWithModels = routes.filter((route) => route.models.length > 0);
  const hasSavedModel = routesWithModels.some((route) => route.models.some((model) => model.id === value));

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={selectId} className="text-white/70 text-[10px]">
        {label}
      </label>
      <select
        id={selectId}
        value={value}
        disabled={disabled}
        aria-describedby={`${helperId}${loadError ? ` ${errorId}` : ''}`}
        onChange={(event) => onChange(event.target.value)}
        className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber disabled:opacity-50"
      >
        <option value="" disabled={routesWithModels.length > 0}>
          {isLoading && routesWithModels.length === 0
            ? 'Loading models…'
            : routesWithModels.length > 0
              ? 'Select a model…'
              : EMPTY_CATALOG_LABEL}
        </option>
        {value && !hasSavedModel && (
          <option value={value} disabled>
            {value} (saved model unavailable)
          </option>
        )}
        {routesWithModels.map((route) => (
          <optgroup key={route.route_id} label={route.label}>
            {route.models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <span id={helperId} className="text-white/50 text-[10px]">
        {helperText}
      </span>
      {loadError && (
        <span id={errorId} role="alert" className="text-red-300 text-[10px]">
          Model list unavailable{onRetry ? <> — <button type="button" onClick={onRetry} className="underline">retry</button></> : null}
        </span>
      )}
    </div>
  );
}
