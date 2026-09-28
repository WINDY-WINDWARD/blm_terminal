/**
 * BLM Script Lab v1 — chart host bridge.
 *
 * - `BandPrimitive`: generic upper/lower fill band drawn on the main pane.
 * - `useScriptSlots`: chart-state slots + head-revision details per panel.
 * - `useScriptedOverlays`: debounced (~1s) script runner. Declared AFTER the
 *   main indicator overlay effect in ChartWidget so teardown/ordering stays
 *   safe. All script artifacts live in their own refs (never in
 *   indicatorSeriesRef) and everything renders on the main pane — v1 does
 *   not create extra panes, so the indicator teardown's pane wipe can't
 *   orphan script output. 3 consecutive run failures auto-disable the slot.
 */
import { useEffect, useMemo, useRef } from 'react';
import {
  HistogramSeries,
  LineSeries,
  LineStyle,
  createSeriesMarkers,
} from 'lightweight-charts';
import type {
  IChartApi,
  IPaneApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesMarker,
  Time,
} from 'lightweight-charts';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  type SavedScriptDetail,
  type ScriptBar,
  type ScriptChartSlot,
  type ScriptFundamentals,
  type ScriptManifest,
  type ScriptMarker,
  type ScriptOutputValues,
  type ScriptRunResult,
} from '@/lib/scripts/types';
import { fetchChartState, fetchScriptDetail } from '@/lib/scripts/api';
import { paramsWithDefaults } from '@/lib/scripts/params';
import { runScript } from '@/lib/scripts/worker';

export const SCRIPT_RENDER_DEBOUNCE_MS = 1000;
/** Consecutive failures before a slot is auto-disabled. */
export const SCRIPT_STRIKE_LIMIT = 3;

// ---------------------------------------------------------------------------
// Band primitive
// ---------------------------------------------------------------------------

export interface BandData {
  times: number[];
  upper: (number | null)[];
  lower: (number | null)[];
  color: string;
}

function withAlpha(hex: string, alphaHex: string): string {
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) return `${hex}${alphaHex}`;
  return hex;
}

class BandRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly getData: () => BandData,
    private readonly series: ISeriesApi<'Candlestick', Time>,
    private readonly chart: IChartApi,
  ) {}

  // CanvasRenderingTarget2D lives in fancy-canvas (a transitive dep), so the
  // draw-target type is extracted from the interface instead of imported.
  draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    const data = this.getData();
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const hRatio = scope.horizontalPixelRatio;
      const vRatio = scope.verticalPixelRatio;
      const pts: { x: number; yu: number; yl: number }[] = [];
      for (let i = 0; i < data.times.length; i++) {
        const u = data.upper[i];
        const l = data.lower[i];
        if (u == null || l == null || !Number.isFinite(u) || !Number.isFinite(l)) continue;
        const x = this.chart.timeScale().timeToCoordinate(data.times[i] as Time);
        const yu = this.series.priceToCoordinate(u);
        const yl = this.series.priceToCoordinate(l);
        if (x == null || yu == null || yl == null) continue;
        pts.push({ x: x * hRatio, yu: yu * vRatio, yl: yl * vRatio });
      }
      if (pts.length === 0) return;
      // Fill between the two lines.
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].yu);
      for (const p of pts) ctx.lineTo(p.x, p.yu);
      for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(pts[i].x, pts[i].yl);
      ctx.closePath();
      ctx.fillStyle = withAlpha(data.color, '2E');
      ctx.fill();
      // Stroke both edges.
      ctx.strokeStyle = data.color;
      ctx.lineWidth = 1 * hRatio;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].yu);
      for (const p of pts) ctx.lineTo(p.x, p.yu);
      ctx.moveTo(pts[0].x, pts[0].yl);
      for (const p of pts) ctx.lineTo(p.x, p.yl);
      ctx.stroke();
    });
  }
}

/** Generic fill band attached to the main candle series. */
export class BandPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick', Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly view: IPrimitivePaneView;
  private readonly renderer: BandRenderer;

  constructor(private data: BandData) {
    // Stable view/renderer pair; data flows through the getter so updates
    // never require re-attaching the primitive.
    this.renderer = new BandRenderer(
      () => this.data,
      // Bound lazily at draw time via fields (set in attached()).
      new Proxy({} as ISeriesApi<'Candlestick', Time>, {
        get: (_t, prop) => (this.series as unknown as Record<string, unknown>)[prop as string],
      }),
      new Proxy({} as IChartApi, {
        get: (_t, prop) => (this.chart as unknown as Record<string, unknown>)[prop as string],
      }),
    );
    this.view = { renderer: () => this.renderer };
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series as ISeriesApi<'Candlestick', Time>;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  updateData(data: BandData): void {
    this.data = data;
    this.requestUpdate?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.chart && this.series ? [this.view] : [];
  }
}

// ---------------------------------------------------------------------------
// Slots data hook
// ---------------------------------------------------------------------------

export interface ResolvedSlot {
  slot: ScriptChartSlot;
  detail: SavedScriptDetail;
}

export function useScriptSlots(panelId: string): {
  slots: ScriptChartSlot[];
  details: Map<number, SavedScriptDetail>;
  slotsLoading: boolean;
  refetchSlots: () => void;
} {
  const slotsQuery = useQuery({
    queryKey: ['script-slots', panelId],
    queryFn: () => fetchChartState(panelId),
    staleTime: 30_000,
    retry: 1,
  });
  const slots = useMemo(
    () => (Array.isArray(slotsQuery.data) ? slotsQuery.data : []),
    [slotsQuery.data],
  );
  // Stable id list: the `queries` array below is a fresh literal every
  // render, so the details Map must NOT depend on it (or any array built
  // from it) — otherwise the Map identity churns each render and the
  // overlay effect's 1s debounce perpetually resets, never painting.
  const slotIds = useMemo(() => slots.map((s) => s.script_id), [slots]);
  const detailsQueries = useQueries({
    queries: slotIds.map((id) => ({
      queryKey: ['script-detail', id],
      queryFn: () => fetchScriptDetail(id),
      staleTime: 60_000,
      retry: 1,
    })),
  });
  const detailsData = detailsQueries.map((q) => q.data);
  const details = useMemo(() => {
    const m = new Map<number, SavedScriptDetail>();
    detailsData.forEach((d, i) => {
      if (d) m.set(slotIds[i], d);
    });
    return m;
    // Deps are element-wise stable (ids + data refs), never array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotIds, ...detailsData]);
  return {
    slots,
    details,
    slotsLoading: slotsQuery.isLoading,
    refetchSlots: () => {
      void slotsQuery.refetch();
    },
  };
}

// ---------------------------------------------------------------------------
// Overlay runner hook
// ---------------------------------------------------------------------------

type ScriptSeries = ISeriesApi<'Line' | 'Histogram', Time>;

export interface ScriptedOverlaysArgs {
  panelId: string;
  symbol: string;
  exchange: string;
  interval: string;
  bars: ScriptBar[];
  slots: ScriptChartSlot[];
  details: Map<number, SavedScriptDetail>;
  fundamentals?: ScriptFundamentals;
  chartRef: React.RefObject<IChartApi | null>;
  mainRef: React.RefObject<ISeriesApi<'Candlestick', Time> | null>;
  onStrikeOut: (slot: ScriptChartSlot, message: string) => void;
}

function toLineData(
  times: number[],
  vals: (number | null | { value?: number | null; color?: string })[],
): { time: Time; value: number; color?: string }[] {
  return times.flatMap((t, i) => {
    const raw = vals[i];
    const value = typeof raw === 'object' && raw !== null ? raw.value : raw;
    if (value == null || !Number.isFinite(value)) return [];
    const color =
      typeof raw === 'object' && raw !== null && typeof raw.color === 'string'
        ? raw.color
        : undefined;
    return [{ time: t as Time, value, ...(color ? { color } : {}) }];
  });
}

export function useScriptedOverlays(args: ScriptedOverlaysArgs): void {
  const {
    panelId,
    symbol,
    exchange,
    interval,
    bars,
    slots,
    details,
    fundamentals,
    chartRef,
    mainRef,
    onStrikeOut,
  } = args;

  const ownedSeries = useRef<ScriptSeries[]>([]);
  const ownedMarkers = useRef<ISeriesMarkersPluginApi<Time>[]>([]);
  const ownedPrimitives = useRef<ISeriesPrimitive<Time>[]>([]);
  const ownedLines = useRef<IPriceLine[]>([]);
  // One shared pane for all overlay:false script outputs (oscillator-style,
  // like the Fx RSI pane). Tracked by object identity: the indicator rebuild
  // removes only its own panes, so this one survives ticks.
  const ownedPaneRef = useRef<IPaneApi<Time> | null>(null);
  const epochRef = useRef(0);
  const strikesRef = useRef(new Map<number, number>());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keyRef = useRef('');
  const onStrikeOutRef = useRef(onStrikeOut);
  onStrikeOutRef.current = onStrikeOut;

  const teardown = () => {
    const chart = chartRef.current;
    const main = mainRef.current;
    // Remove the script pane first — its series die with it; the bags are
    // cleared below (stale removes are try/catch-guarded).
    const pane = ownedPaneRef.current;
    if (pane && chart) {
      const idx = chart.panes().indexOf(pane);
      if (idx > 0) {
        try {
          chart.removePane(idx);
        } catch {
          /* already removed */
        }
      }
      ownedPaneRef.current = null;
    }
    for (const s of ownedSeries.current) {
      try {
        chart?.removeSeries(s);
      } catch {
        /* already removed */
      }
    }
    ownedSeries.current = [];
    for (const m of ownedMarkers.current) {
      try {
        m.detach();
      } catch {
        /* already detached */
      }
    }
    ownedMarkers.current = [];
    for (const p of ownedPrimitives.current) {
      try {
        main?.detachPrimitive(p);
      } catch {
        /* already detached */
      }
    }
    ownedPrimitives.current = [];
    for (const l of ownedLines.current) {
      try {
        main?.removePriceLine(l);
      } catch {
        /* already removed */
      }
    }
    ownedLines.current = [];
  };

  /** Lazily create (or reuse) the shared script oscillator pane. */
  const ensureScriptPane = (chart: IChartApi): number => {
    const existing = ownedPaneRef.current;
    if (existing) {
      const idx = chart.panes().indexOf(existing);
      if (idx > 0) return idx;
      ownedPaneRef.current = null;
    }
    chart.addPane();
    const panes = chart.panes();
    const created = panes[panes.length - 1];
    created.setStretchFactor(0.35);
    ownedPaneRef.current = created;
    return panes.length - 1;
  };

  /** Outputs that belong on the script pane (Fx-style separate graph). */
  const isPaneOutput = (o: { kind: string; overlay?: boolean }): boolean =>
    o.overlay === false && (o.kind === 'line' || o.kind === 'histogram' || o.kind === 'priceline');

  // Unmount: never leave script artifacts on a dead chart.
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      teardown();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    const epoch = ++epochRef.current;
    if (timerRef.current) clearTimeout(timerRef.current);

    // Symbol/interval/panel switches must clear immediately — stale-symbol
    // scripts over fresh candles would mislead. Pure data refreshes keep
    // the old render until the debounced re-run lands (no flicker).
    const key = `${panelId}|${symbol}|${interval}`;
    if (key !== keyRef.current) {
      keyRef.current = key;
      strikesRef.current.clear();
      teardown();
    }

    const chart = chartRef.current;
    const main = mainRef.current;
    const active: ResolvedSlot[] = [];
    for (const slot of slots) {
      if (!slot.enabled) continue;
      const detail = details.get(slot.script_id);
      if (detail?.head) active.push({ slot, detail });
    }
    if (!chart || !main || active.length === 0 || bars.length === 0) {
      if (active.length === 0) teardown();
      return;
    }

    timerRef.current = setTimeout(() => {
      void (async () => {
        if (epoch !== epochRef.current) return;
        // Single swap: drop the previous render before painting the new one.
        teardown();
        // One shared oscillator pane for all overlay:false outputs. Computed
        // across every active slot so the pane persists while any slot needs
        // it (markers/band stay on main in v1 even when overlay:false).
        const needPane = active.some(({ detail }) =>
          ((detail.head?.manifest as ScriptManifest | undefined)?.outputs ?? []).some(isPaneOutput),
        );
        const paneIdx = needPane ? ensureScriptPane(chart) : null;
        const runBars = bars;
        const runTimes = runBars.map((b) => b.time);
        for (const { slot, detail } of active) {
          if (epoch !== epochRef.current) return;
          const manifest = detail.head?.manifest as ScriptManifest | undefined;
          const code = detail.head?.code;
          if (!manifest || !code) continue;
          const params = paramsWithDefaults(manifest, slot.param_values);
          const ctx = {
            bars: runBars,
            params,
            symbol,
            exchange,
            interval,
            ...(manifest.needs_fundamentals && fundamentals
              ? { fundamentals }
              : {}),
          };
          let result: ScriptRunResult;
          try {
            result = await runScript({ code, manifest, ctx });
          } catch (e) {
            result = {
              ok: false,
              code: 'E_RUNTIME',
              message: e instanceof Error ? e.message : 'script run failed',
            };
          }
          if (epoch !== epochRef.current) return;
          const strike = (message: string) => {
            const n = (strikesRef.current.get(slot.script_id) ?? 0) + 1;
            if (n >= SCRIPT_STRIKE_LIMIT) {
              strikesRef.current.delete(slot.script_id);
              onStrikeOutRef.current(slot, message);
            } else {
              strikesRef.current.set(slot.script_id, n);
            }
          };
          if (!result.ok) {
            strike(result.message);
            continue;
          }
          strikesRef.current.delete(slot.script_id);
          try {
            paintOutputs(chart, main, runTimes, manifest, result.values, {
              series: ownedSeries.current,
              markers: ownedMarkers.current,
              primitives: ownedPrimitives.current,
              lines: ownedLines.current,
            }, paneIdx);
          } catch (e) {
            // A throwing paint must not leave a torn-down chart with no
            // output and no error: count it as a run failure so the 3-strike
            // path surfaces it in the UI.
            strike(e instanceof Error ? `paint failed: ${e.message}` : 'paint failed');
          }
        }
      })();
    }, SCRIPT_RENDER_DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelId, symbol, exchange, interval, bars, slots, details, fundamentals]);
}

interface OwnedBags {
  series: ScriptSeries[];
  markers: ISeriesMarkersPluginApi<Time>[];
  primitives: ISeriesPrimitive<Time>[];
  lines: IPriceLine[];
}

function paintOutputs(
  chart: IChartApi,
  main: ISeriesApi<'Candlestick', Time>,
  times: number[],
  manifest: ScriptManifest,
  values: Record<string, ScriptOutputValues>,
  bags: OwnedBags,
  paneIdx: number | null,
): void {
  const onPane = (o: { kind: string; overlay?: boolean }): boolean =>
    paneIdx !== null &&
    o.overlay === false &&
    (o.kind === 'line' || o.kind === 'histogram' || o.kind === 'priceline');
  // Host series for pane pricelines: first pane line wins; a hidden anchor
  // covers pane-priceline-only outputs (e.g. bare levels).
  let paneHost: ISeriesApi<'Line', Time> | null = null;
  const ensurePaneHost = (): ISeriesApi<'Line', Time> => {
    if (!paneHost) {
      paneHost = chart.addSeries(
        LineSeries,
        {
          color: '#00000000',
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          visible: false,
        },
        paneIdx as number,
      );
      bags.series.push(paneHost);
    }
    return paneHost;
  };
  for (const o of manifest.outputs) {
    const v = values[o.id];
    if (v === undefined) continue;
    const color = o.color ?? '#FFB900';
    const targetPane = onPane(o) ? (paneIdx as number) : undefined;
    switch (o.kind) {
      case 'line': {
        if (!Array.isArray(v)) break;
        const s = chart.addSeries(LineSeries, {
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }, targetPane);
        s.setData(toLineData(times, v as (number | null | { value?: number | null; color?: string })[]));
        bags.series.push(s);
        if (targetPane !== undefined && !paneHost) paneHost = s;
        break;
      }
      case 'histogram': {
        if (!Array.isArray(v)) break;
        const s = chart.addSeries(HistogramSeries, {
          priceScaleId: '',
          priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
        }, targetPane);
        s.setData(
          (v as (number | null)[]).flatMap((val, i) =>
            val == null || !Number.isFinite(val)
              ? []
              : [{
                  time: times[i] as Time,
                  value: val,
                  color: val >= 0 ? '#26a69a' : '#ef5350',
                }],
          ),
        );
        bags.series.push(s);
        break;
      }
      case 'markers': {
        if (!Array.isArray(v)) break;
        const markers: SeriesMarker<Time>[] = (v as ScriptMarker[][]).flatMap((cell, i) =>
          (cell ?? []).map((m) => ({
            time: times[i] as Time,
            position: m.pos,
            shape: m.shape,
            color: m.color ?? color,
            ...(m.text ? { text: m.text } : {}),
          })),
        );
        bags.markers.push(createSeriesMarkers(main, markers));
        break;
      }
      case 'priceline': {
        if (typeof v !== 'number' || !Number.isFinite(v)) break;
        const host = targetPane !== undefined ? ensurePaneHost() : main;
        bags.lines.push(
          host.createPriceLine({
            price: v,
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: o.id,
          }),
        );
        break;
      }
      case 'band': {
        const upperVals = values[o.upper ?? ''] as (number | null)[] | undefined;
        const lowerVals = values[o.lower ?? ''] as (number | null)[] | undefined;
        if (!Array.isArray(upperVals) || !Array.isArray(lowerVals)) break;
        const prim = new BandPrimitive({ times, upper: upperVals, lower: lowerVals, color });
        main.attachPrimitive(prim);
        bags.primitives.push(prim);
        break;
      }
      default:
        break;
    }
  }
}
