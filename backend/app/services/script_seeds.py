"""Builtin Script Lab seeds (is_builtin, non-deletable, per-user lazy seed)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.script import SavedScript, ScriptRevision
from app.schemas.script import validate_script

_SEED_SMA = """// @blm-script {"name":"SMA-20/50","version":1,"description":"Two simple moving averages over close.","params":[{"key":"len1","label":"Fast length","type":"int","default":20,"min":2,"max":200},{"key":"len2","label":"Slow length","type":"int","default":50,"min":2,"max":200}],"outputs":[{"id":"smaFast","kind":"line"},{"id":"smaSlow","kind":"line"}]}
function calculate(ctx) {
  var closes = ctx.bars.map(function (b) { return b.c; });
  return {
    smaFast: BLM.sma(closes, ctx.params.len1),
    smaSlow: BLM.sma(closes, ctx.params.len2)
  };
}
"""

_SEED_EMA_CROSS = """// @blm-script {"name":"EMA cross + markers","version":1,"description":"Fast/slow EMA cross with arrow markers.","params":[{"key":"fast","label":"Fast length","type":"int","default":9,"min":2,"max":100},{"key":"slow","label":"Slow length","type":"int","default":21,"min":3,"max":200}],"outputs":[{"id":"emaFast","kind":"line"},{"id":"emaSlow","kind":"line"},{"id":"crosses","kind":"markers"}]}
function calculate(ctx) {
  var closes = ctx.bars.map(function (b) { return b.c; });
  var fast = BLM.ema(closes, ctx.params.fast);
  var slow = BLM.ema(closes, ctx.params.slow);
  var marks = ctx.bars.map(function (b, i) {
    var out = [];
    if (i > 0 && fast[i] != null && slow[i] != null && fast[i - 1] != null && slow[i - 1] != null) {
      if (fast[i - 1] <= slow[i - 1] && fast[i] > slow[i]) {
        out.push({ pos: "belowBar", shape: "arrowUp", text: "BUY" });
      } else if (fast[i - 1] >= slow[i - 1] && fast[i] < slow[i]) {
        out.push({ pos: "aboveBar", shape: "arrowDown", text: "SELL" });
      }
    }
    return out;
  });
  return { emaFast: fast, emaSlow: slow, crosses: marks };
}
"""

_SEED_RSI = """// @blm-script {"name":"RSI-14 + 70/30","version":1,"description":"RSI oscillator with overbought/oversold lines.","params":[{"key":"period","label":"RSI period","type":"int","default":14,"min":2,"max":100},{"key":"overbought","label":"Overbought","type":"int","default":70,"min":50,"max":100},{"key":"oversold","label":"Oversold","type":"int","default":30,"min":0,"max":50}],"outputs":[{"id":"rsiLine","kind":"line","overlay":false,"pane":"new"},{"id":"obLine","kind":"priceline"},{"id":"osLine","kind":"priceline"}]}
function calculate(ctx) {
  var closes = ctx.bars.map(function (b) { return b.c; });
  return {
    rsiLine: BLM.rsi(closes, ctx.params.period),
    obLine: ctx.params.overbought,
    osLine: ctx.params.oversold
  };
}
"""

_SEED_VWAP = """// @blm-script {"name":"Session VWAP","version":1,"description":"Cumulative volume-weighted average price.","params":[],"outputs":[{"id":"vwap","kind":"line"}]}
function calculate(ctx) {
  var cumPV = 0, cumV = 0;
  return {
    vwap: ctx.bars.map(function (b) {
      var tp = (b.h + b.l + b.c) / 3;
      cumPV += tp * b.v;
      cumV += b.v;
      return cumV > 0 ? cumPV / cumV : null;
    })
  };
}
"""

_SEED_ATR_BAND = """// @blm-script {"name":"ATR level","version":1,"description":"Close plus/minus ATR multiple.","params":[{"key":"period","label":"ATR period","type":"int","default":14,"min":2,"max":100},{"key":"mult","label":"Multiple","type":"number","default":2.0,"min":0.5,"max":5.0,"step":0.1}],"outputs":[{"id":"atrUpper","kind":"line"},{"id":"atrLower","kind":"line"}]}
function calculate(ctx) {
  var highs = ctx.bars.map(function (b) { return b.h; });
  var lows = ctx.bars.map(function (b) { return b.l; });
  var closes = ctx.bars.map(function (b) { return b.c; });
  var a = BLM.atr(highs, lows, closes, ctx.params.period);
  return {
    atrUpper: ctx.bars.map(function (b, i) { return a[i] == null ? null : b.c + ctx.params.mult * a[i]; }),
    atrLower: ctx.bars.map(function (b, i) { return a[i] == null ? null : b.c - ctx.params.mult * a[i]; })
  };
}
"""

SEEDS: tuple[tuple[str, str, str], ...] = (
    ("SMA-20/50", "Two simple moving averages over close.", _SEED_SMA),
    ("EMA cross + markers", "Fast/slow EMA cross with arrow markers.", _SEED_EMA_CROSS),
    ("RSI-14 + 70/30", "RSI oscillator with overbought/oversold lines.", _SEED_RSI),
    ("Session VWAP", "Cumulative volume-weighted average price.", _SEED_VWAP),
    ("ATR level", "Close plus/minus ATR multiple.", _SEED_ATR_BAND),
)


async def ensure_builtin_seeds(db: AsyncSession, user_id: int) -> None:
    """Create any missing builtin seeds for this user (idempotent)."""
    changed = False
    for name, description, code in SEEDS:
        q = select(SavedScript).where(SavedScript.user_id == user_id, SavedScript.name == name)
        if (await db.execute(q)).scalar_one_or_none() is not None:
            continue
        manifest, errors = validate_script(code)
        if manifest is None or errors:  # pragma: no cover - seeds are static-valid
            raise RuntimeError(f"builtin seed {name!r} failed validation: {errors}")
        script = SavedScript(user_id=user_id, name=name, description=description, is_builtin=True)
        db.add(script)
        await db.flush()
        rev = ScriptRevision(
            script_id=script.id, rev_no=1, manifest=manifest.model_dump(),
            code=code, note="builtin seed",
        )
        db.add(rev)
        await db.flush()
        script.head_rev_id = rev.id
        changed = True
    if changed:
        await db.commit()
