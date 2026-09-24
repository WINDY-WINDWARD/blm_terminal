/**
 * BLM Script Lab v1 — dev fixture scripts (single source of truth).
 * Consumed by the dev-only /dev-scripts page AND fixtures.test.ts so the
 * page and the suite can never drift apart. Never shipped to users
 * (the page 404s in production builds).
 */
export interface DevFixture {
  name: string;
  desc: string;
  code: string;
}

export const DEV_FIXTURES: DevFixture[] = [
  {
    name: 'SMA line',
    desc: 'Line output: 20-bar simple moving average of closes.',
    code: `// @blm-script {"name":"Fixture: SMA line","version":1,"params":[{"key":"len","type":"int","default":20,"min":2,"max":100}],"outputs":[{"id":"sma","kind":"line","color":"#FFB900"}]}
function calculate(ctx) { return { sma: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) }; }`,
  },
  {
    name: 'Volume histogram',
    desc: 'Histogram output: raw bar volumes.',
    code: `// @blm-script {"name":"Fixture: volume histogram","version":1,"outputs":[{"id":"vol","kind":"histogram","color":"#3a3a3a"}]}
function calculate(ctx) { return { vol: ctx.bars.map(function (b) { return b.v; }) }; }`,
  },
  {
    name: 'EMA cross markers',
    desc: 'Markers output: arrowUp/arrowDown on 9/21 EMA crosses.',
    code: `// @blm-script {"name":"Fixture: EMA cross markers","version":1,"params":[{"key":"fast","type":"int","default":9,"min":2,"max":50},{"key":"slow","type":"int","default":21,"min":3,"max":100}],"outputs":[{"id":"sig","kind":"markers"}]}
function calculate(ctx) { var c = ctx.bars.map(function (b) { return b.c; }); var f = BLM.ema(c, ctx.params.fast); var s = BLM.ema(c, ctx.params.slow); return { sig: ctx.bars.map(function (b, i) { if (f[i] === null || s[i] === null || f[i-1] === null || s[i-1] === null) return []; if (f[i-1] <= s[i-1] && f[i] > s[i]) return [{ pos: 'belowBar', shape: 'arrowUp', text: 'B', color: '#00ff00' }]; if (f[i-1] >= s[i-1] && f[i] < s[i]) return [{ pos: 'aboveBar', shape: 'arrowDown', text: 'S', color: '#ff0000' }]; return []; }) }; }`,
  },
  {
    name: 'Last-close priceline',
    desc: 'Priceline output: single finite number (last close).',
    code: `// @blm-script {"name":"Fixture: last-close priceline","version":1,"outputs":[{"id":"px","kind":"priceline","color":"#FFB900"}]}
function calculate(ctx) { return { px: ctx.bars[ctx.bars.length - 1].c }; }`,
  },
  {
    name: 'Bollinger band',
    desc: 'Band output referencing two sibling line outputs.',
    code: `// @blm-script {"name":"Fixture: Bollinger band","version":1,"params":[{"key":"len","type":"int","default":20,"min":2,"max":100},{"key":"mult","type":"number","default":2,"min":0.5,"max":4,"step":0.1}],"outputs":[{"id":"basis","kind":"line"},{"id":"upper","kind":"line"},{"id":"lower","kind":"line"},{"id":"bb","kind":"band","upper":"upper","lower":"lower"}]}
function calculate(ctx) { var r = BLM.bb(ctx.bars.map(function (b) { return b.c; }), ctx.params.len, ctx.params.mult); return { basis: r.basis, upper: r.upper, lower: r.lower, bb: r.basis }; }`,
  },
  {
    name: 'PE ribbon (fundamentals)',
    desc: 'needs_fundamentals script. Dry-run ships no fundamentals ctx, so the constant is null here; on-chart with data consent it renders the PE level.',
    code: `// @blm-script {"name":"Fixture: PE ribbon","version":1,"needs_fundamentals":true,"outputs":[{"id":"pe","kind":"line","color":"#7dd3fc"}]}
function calculate(ctx) { var pe = ctx.fundamentals && ctx.fundamentals.ratios ? ctx.fundamentals.ratios.pe : null; return { pe: ctx.bars.map(function () { return typeof pe === 'number' ? pe : null; }) }; }`,
  },
  {
    name: 'Runtime error',
    desc: 'Expected failure: throw maps to E_RUNTIME with message.',
    code: `// @blm-script {"name":"Fixture: runtime error","version":1,"outputs":[{"id":"a","kind":"line"}]}
function calculate(ctx) { throw new Error('fixture boom'); }`,
  },
];
