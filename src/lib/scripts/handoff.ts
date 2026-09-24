/**
 * BLM Script Lab v1 — pure helpers for the AI ↔ chart handoffs.
 * Kept dependency-free so they are trivially unit-testable.
 */

/**
 * Resolve which chart panel an accepted script card should land on:
 * focused CHART panel wins, else the first CHART panel on the grid,
 * else the focused panel (or panel-1) as a last resort — the ChartWidget
 * handoff consumer ignores non-matching panels, so this never mispaints.
 */
export function resolveChartPanel(
  panels: Record<string, string>,
  focused: string | null,
): string {
  if (focused && panels[focused] === 'CHART') return focused;
  const first = Object.keys(panels).find((k) => panels[k] === 'CHART');
  if (first) return first;
  return focused || 'panel-1';
}

/** Find the AI panel on the grid, if any (for the focus-or-popout refine path). */
export function findAiPanel(panels: Record<string, string>): string | null {
  return Object.keys(panels).find((k) => panels[k] === 'AI') ?? null;
}

/** Script-scoped refine prompt prefilled into the AI input by the chart Σ menu. */
export function buildRefinePrompt(
  name: string,
  scriptId: number,
  revNo: number | null,
): string {
  return `Refine chart script "${name}" (id ${scriptId}${revNo != null ? `, rev ${revNo}` : ''}): `;
}
