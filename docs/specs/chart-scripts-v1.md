# BLM Chart Scripts — Spec v1 (normative)

**Status:** normative for v1. Anything not in this document is not supported in v1.
**Design target:** full Pine-parity eventually, delivered through versioned spec revisions.
This document defines spec version `1`. Scripts declaring any other `version`
MUST be rejected by the validator with an explicit "requires spec v2" error.

## 0. Philosophy

- **JS, not Pine.** Scripts are plain synchronous JavaScript executed in a
  sandboxed Web Worker. No Pine imports, no transpiler.
- **AI-friendly.** The AI owns code. The user owns intent + parameters.
  There is no user-facing code surface: no editor, no paste-a-script.
- **Declarative manifest.** A `@blm-script` JSON header declares name,
  params, outputs, and data needs. The runner validates the manifest before
  executing a single line of user code.
- **Pure + bar-aligned.** `calculate(ctx)` is pure: same inputs, same outputs.
  No network, no timers, no randomness, no DOM.

## 1. Manifest (`@blm-script` header JSON)

Every script MUST start with a single-line JSON header comment:

```js
// @blm-script {"name":"...","version":1,...}
```

| Field               | Type    | Required | Constraints                                          |
|---------------------|---------|----------|------------------------------------------------------|
| `name`              | string  | yes      | 1–64 chars                                           |
| `version`           | number  | yes      | MUST be `1` (anything else → "requires spec v2")     |
| `description`       | string  | no       | ≤280 chars, plain language, shown on cards           |
| `params`            | array   | no       | ≤24 entries, see §2                                  |
| `outputs`           | array   | yes      | 1–8 entries, see §3                                  |
| `needs_fundamentals`| boolean | no       | default `false`; when true, `ctx.fundamentals` is set|

### 1.1 Reserved for v2

The validator MUST reject these manifest keys with "requires spec v2":
`drawings`, `alerts`, `strategy`, `timeframe`, `symbol`.
(`timeframe`/`symbol` are reserved param *types*; scripts always run on the
host chart's symbol + interval.)

## 2. Params

Each param: `{key, label?, type, default, ...}`.

| Type     | Extra fields                          | Example default |
|----------|---------------------------------------|-----------------|
| `int`    | `min`, `max`, `step` (default 1)      | `14`            |
| `number` | `min`, `max`, `step`                  | `2.0`           |
| `bool`   | —                                     | `true`          |
| `select` | `options`: string[] (≥2)              | `"close"`       |
| `color`  | hex string `#rrggbb`                  | `"#FFB900"`     |
| `source` | one of `open high low close hlc3 hl2 ohlc4 volume` | `"close"` |

Rules:

- `key` MUST be a valid JS identifier, unique within the script.
- `default` MUST satisfy the type + range constraints (validator enforces).
- Every param key MUST be referenced by the code (static check); unreferenced
  params are a validation error (dead knobs are a UX bug).
- Param count ≤ 24.

## 3. Outputs

Each output: `{id, kind, ...}`. `id` MUST be a valid JS identifier, unique,
and MUST appear as a key in the object returned by `calculate`.

| Kind        | Placement                              | Value shape per bar                              |
|-------------|----------------------------------------|--------------------------------------------------|
| `line`      | `overlay: true` (default) or `pane: "new"` | `number \| null` (null = gap)              |
| `histogram` | overlay w/ own scale, or `pane: "new"` | `number \| null`                                 |
| `markers`   | on price                               | `Marker[]` (empty = none), see §3.1              |
| `priceline` | horizontal line                        | single `number` (const) — or the last value rule |
| `band`      | fill between two named series          | `{upper: <lineId>, lower: <lineId>}` + style     |

Output count ≤ 8. Band references MUST name two `line` outputs of the same script.

### 3.1 Markers

```ts
type Marker = {
  pos: "aboveBar" | "belowBar";   // v1: bar-relative only
  shape: "arrowUp" | "arrowDown" | "circle" | "square";
  text?: string;                  // ≤8 chars
  color?: string;                 // hex, defaults to series color
};
```

Returned as `{[outputId]: Marker[][]}` — an array per bar (usually empty).

## 4. `calculate(ctx)` contract

```js
function calculate(ctx) {
  // ... pure computation ...
  return { myLine: [...], myMarkers: [...] };
}
```

- MUST be a top-level `function calculate(ctx)`. No imports, no `require`,
  no access to anything outside `ctx`, frozen `BLM`, and `Math`. The worker
  additionally shadows `self/postMessage/fetch/importScripts/XMLHttpRequest/
  WebSocket/timers/...` with `undefined`, so network/exfiltration/loader
  globals are unreachable even if referenced.
- MUST be synchronous. `async`, generators, classes, `eval`, and the
  `Function` constructor are rejected (static check).
- MUST return an object with exactly the manifest's output ids (extra keys rejected).
- Series arrays MUST have length === `ctx.bars.length` (`number|null` per bar;
  markers: array per bar). Length mismatch is a runtime error.
- Execution budget: ≤2000ms wall (watchdog terminates the worker).
- Code size ≤64KB. Bars supplied ≤2000 (host truncates).

### 4.1 `ctx` shape

```ts
type Ctx = {
  bars: Bar[];            // ascending time, ≤2000
  params: Record<string, number | boolean | string>;
  fundamentals?: {
    quarterly: Array<{      // ascending by period, step-filled across bars
      period: string;       // e.g. "2024Q3"
      sales?: number | null;
      opProfit?: number | null;
      netProfit?: number | null;
      eps?: number | null;
    }>;
    ratios: {               // snapshot constants for the symbol
      pe?: number | null;
      roe?: number | null;
      roce?: number | null;
      marketCapCr?: number | null;
    };
  };
  symbol: string;           // host chart symbol
  exchange: string;         // host chart exchange
  interval: string;         // host chart interval
};

type Bar = {
  time: number;             // seconds (lightweight-charts Time)
  o: number; h: number; l: number; c: number;
  v: number;                // volume; flat on live edge (ticks are LTP-only)
  live?: boolean;           // true ONLY on the in-memory brewing bar
};
```

- `live: true` on the brewing bar is the v1 analogue of Pine's
  `barstate.islast`. Scripts MAY branch on it; most will ignore it.
- `fundamentals` is present ONLY when `needs_fundamentals: true` AND the
  user has granted data consent (Safe Mode → script does not run; the UI
  shows a "needs data consent" row state instead).
- Quarterly rows are step-filled: each bar sees the latest quarter with
  `period <= barTime` (host pre-computes; scripts see plain arrays).

## 5. Stdlib (`BLM.*`)

Frozen global. Semantics MUST be identical to
`src/lib/indicators/calculations.ts`:

`sma(values, period)`, `ema(values, period)`, `rsi(closes, period)`,
`macd(closes, fast, slow, signal)` → `{macdLine, signalLine, hist}`,
`bb(closes, period, mult)` → `{basis, upper, lower}`,
`atr(highs, lows, closes, period)`, `stoch(highs, lows, closes, k, slowing, d)`
→ `{k, d}`, `obv(closes, volumes)`, `vwap(highs, lows, closes, volumes)`,
`highest(values, period)`, `lowest(values, period)`,
`change(values)` (bar-to-bar diff), `nz(value, fallback=0)`.

All series functions return `(number|null)[]` with `null` warmup — never throw
on short input. `na` handling follows the existing engine: propagate `null`.

## 6. Limits (enforced)

| Limit            | Value  | Enforced by          |
|------------------|--------|----------------------|
| code size        | ≤64KB  | validator (static)   |
| params           | ≤24    | validator (manifest) |
| outputs          | ≤8     | validator (manifest) |
| bars per run     | ≤2000  | host (truncates)     |
| exec time        | ≤2000ms| worker watchdog      |

## 7. Error taxonomy

| Code                    | Meaning                                          |
|-------------------------|--------------------------------------------------|
| `E_MANIFEST_JSON`       | header missing or unparsable                     |
| `E_MANIFEST_SCHEMA`     | schema violation (message names the field)       |
| `E_VERSION`             | `version != 1` → "requires spec v2"              |
| `E_V2_KIND`             | `drawings\|alerts\|strategy` etc → "requires spec v2" |
| `E_PARAM`               | bad default / unreferenced param / dup key       |
| `E_OUTPUT`              | unknown kind / bad band refs / count exceeded    |
| `E_STATIC`              | `async`/class/import/`eval`/`Function`/`calculate` missing |
| `E_LENGTH`              | returned series length ≠ bars length             |
| `E_RUNTIME`             | throw during calculate (message + line)          |
| `E_TIMEOUT`             | exceeded 2000ms                                  |
| `E_LIMIT`               | code >64KB                                       |

## 8. Versioning policy

- v1 is frozen by this document. New capabilities arrive as a new spec
  version with its own document; the validator rejects unknown versions.
- Revisions (user scripts) are immutable snapshots; rollback re-points the
  head, never deletes history.
- Param auto-migration: surviving keys keep their values across revisions;
  new keys take manifest defaults; removed keys are dropped.

## 9. Dev fixtures (dev-only, excluded from release)

- `src/app/dev-scripts/page.tsx` renders 7 visual fixtures (one per output
  kind: line, histogram, markers, priceline, band; plus a
  `needs_fundamentals` script and an `E_RUNTIME` error script), each executed
  via `validateScript` against the 120-bar seeded fixture.
- The page calls `notFound()` when `NODE_ENV === 'production'`, so release
  builds (production Next build) serve a 404; fixtures never ship to users.
