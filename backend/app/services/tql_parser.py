"""Ticker Query Language (TQL) parser and AST evaluator.

Syntax overview
---------------
  FIELD OP VALUE
  FIELD IN (VALUE, VALUE, ...)
  EXPR AND EXPR
  EXPR OR EXPR
  NOT EXPR
  ( EXPR )

Field naming
------------
  Plain field name uses the default_interval passed at evaluation time.
  Interval-prefixed field: <interval>:<field>  e.g.  1h:RSI  W:ATR

Supported fields (case-insensitive)
------------------------------------
  RSI           indicators_by_interval[iv]['rsi_14']
  ATR           indicators_by_interval[iv]['atr_percent']
  MACD          indicators_by_interval[iv]['macd']
  MACDSignal    indicators_by_interval[iv]['macd_signal']
  MACDHist      indicators_by_interval[iv]['macd_histogram']
  BBWidth       indicators_by_interval[iv]['bb_width']
  BBSqueeze     indicators_by_interval[iv]['bb_squeeze']  (bool)
  HV20          indicators_by_interval[iv]['hv_20']
  HV60          indicators_by_interval[iv]['hv_60']
  Sharpe60      indicators_by_interval[iv]['sharpe_60']
  Sharpe126     indicators_by_interval[iv]['sharpe_126']
  Change        data['change_today']
  Volume        data['volume_ratio']
  Close         data['close']
  Sector        data['sector']
  Industry      data['industry']
  PE            data['pe']
  MomentumScore data['momentum_score']  (may be absent)
  Return1w      data['returns']['1w']
  Return1m      data['returns']['1m']
  Return3m      data['returns']['3m']
  Return6m      data['returns']['6m']
  Return1y      data['returns']['1y']
  From52wHigh   data['pos_52w']['pct_from_52w_high']
  From52wLow    data['pos_52w']['pct_from_52w_low']
  Symbol        data['symbol']
  DataPoints    data['data_points']

Operators
---------
  >  <  >=  <=  =  !=  IN

Examples
--------
  RSI > 60 AND Change > 2
  1h:RSI > 65 AND W:RSI > 55
  Sector IN ("Banks", "IT") AND Volume > 2
  NOT BBSqueeze AND ATR < 3
  (Return1m > 10 OR Return3m > 20) AND PE < 30
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Any


# ─── Token types ─────────────────────────────────────────────────────────────

class TT:
    FIELD    = "FIELD"     # identifier (possibly interval-prefixed)
    OP       = "OP"        # > < >= <= = !=
    IN       = "IN"
    AND      = "AND"
    OR       = "OR"
    NOT      = "NOT"
    LPAREN   = "LPAREN"
    RPAREN   = "RPAREN"
    COMMA    = "COMMA"
    STRING   = "STRING"
    NUMBER   = "NUMBER"
    BOOL     = "BOOL"
    EOF      = "EOF"


@dataclass
class Token:
    type: str
    value: Any


# ─── Lexer ────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
    \s*
    (?:
        (>=|<=|!=|>|<|=)                        # operators
      | (\()                                      # LPAREN
      | (\))                                      # RPAREN
      | (,)                                       # COMMA
      | "([^"]*)"                                 # double-quoted string
      | '([^']*)'                                 # single-quoted string
      | (\d+[A-Za-z][A-Za-z0-9]*:[A-Za-z_][A-Za-z0-9_]*)  # interval-prefixed field e.g. 1h:RSI
      | (-?\d+(?:\.\d+)?)                         # number
      | ([A-Za-z_][A-Za-z0-9_:.]*)               # identifier / field
    )
    """,
    re.VERBOSE,
)

_KEYWORDS: dict[str, str] = {
    "and": TT.AND,
    "or":  TT.OR,
    "not": TT.NOT,
    "in":  TT.IN,
    "true":  TT.BOOL,
    "false": TT.BOOL,
}


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise TQLSyntaxError(f"Unexpected character at position {pos}: {text[pos]!r}")
        pos = m.end()
        op, lp, rp, comma, dqs, sqs, iv_field, num, ident = m.groups()
        if op:
            tokens.append(Token(TT.OP, op))
        elif lp:
            tokens.append(Token(TT.LPAREN, "("))
        elif rp:
            tokens.append(Token(TT.RPAREN, ")"))
        elif comma:
            tokens.append(Token(TT.COMMA, ","))
        elif dqs is not None:
            tokens.append(Token(TT.STRING, dqs))
        elif sqs is not None:
            tokens.append(Token(TT.STRING, sqs))
        elif iv_field is not None:
            # Interval-prefixed field like "1h:RSI" or "1d:ATR" — always a FIELD token
            tokens.append(Token(TT.FIELD, iv_field))
        elif num is not None:
            tokens.append(Token(TT.NUMBER, float(num) if "." in num else int(num)))
        elif ident:
            lower = ident.lower()
            tt = _KEYWORDS.get(lower, TT.FIELD)
            if tt == TT.BOOL:
                tokens.append(Token(TT.BOOL, lower == "true"))
            else:
                tokens.append(Token(tt, ident if tt == TT.FIELD else ident.upper()))
    tokens.append(Token(TT.EOF, None))
    return tokens


# ─── AST nodes ────────────────────────────────────────────────────────────────

@dataclass
class CompareNode:
    field: str          # may include interval prefix e.g. "1h:RSI"
    op: str
    value: Any


@dataclass
class InNode:
    field: str
    values: list[Any]


@dataclass
class AndNode:
    left: Any
    right: Any


@dataclass
class OrNode:
    left: Any
    right: Any


@dataclass
class NotNode:
    expr: Any


# ─── Parser ───────────────────────────────────────────────────────────────────

class TQLSyntaxError(ValueError):
    pass


class Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _consume(self, *types: str) -> Token:
        tok = self._tokens[self._pos]
        if types and tok.type not in types:
            raise TQLSyntaxError(
                f"Expected {types} but got {tok.type!r} ({tok.value!r})"
            )
        self._pos += 1
        return tok

    def parse(self) -> Any:
        node = self._parse_or()
        self._consume(TT.EOF)
        return node

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self._peek().type == TT.OR:
            self._consume(TT.OR)
            right = self._parse_and()
            left = OrNode(left, right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_not()
        while self._peek().type == TT.AND:
            self._consume(TT.AND)
            right = self._parse_not()
            left = AndNode(left, right)
        return left

    def _parse_not(self) -> Any:
        if self._peek().type == TT.NOT:
            self._consume(TT.NOT)
            return NotNode(self._parse_not())
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        tok = self._peek()

        if tok.type == TT.LPAREN:
            self._consume(TT.LPAREN)
            node = self._parse_or()
            self._consume(TT.RPAREN)
            return node

        if tok.type == TT.FIELD:
            field_name = self._consume(TT.FIELD).value
            next_tok = self._peek()

            if next_tok.type == TT.IN:
                self._consume(TT.IN)
                self._consume(TT.LPAREN)
                values = [self._parse_literal()]
                while self._peek().type == TT.COMMA:
                    self._consume(TT.COMMA)
                    values.append(self._parse_literal())
                self._consume(TT.RPAREN)
                return InNode(field_name, values)

            if next_tok.type == TT.OP:
                op = self._consume(TT.OP).value
                value = self._parse_literal()
                return CompareNode(field_name, op, value)

            # bare boolean field e.g. BBSqueeze (treat as = true)
            return CompareNode(field_name, "=", True)

        if tok.type == TT.BOOL:
            self._consume(TT.BOOL)
            return CompareNode("_literal", "=", tok.value)

        raise TQLSyntaxError(f"Unexpected token {tok.type!r} ({tok.value!r})")

    def _parse_literal(self) -> Any:
        tok = self._peek()
        if tok.type == TT.NUMBER:
            return self._consume(TT.NUMBER).value
        if tok.type == TT.STRING:
            return self._consume(TT.STRING).value
        if tok.type == TT.BOOL:
            return self._consume(TT.BOOL).value
        if tok.type == TT.FIELD:
            # unquoted string value (e.g. Sector = Banks)
            return self._consume(TT.FIELD).value
        raise TQLSyntaxError(f"Expected a value but got {tok.type!r} ({tok.value!r})")


def parse_tql(query: str) -> Any:
    """Parse a TQL query string and return an AST root node.

    Also validates that every field reference (including interval prefix) is
    well-formed — raises TQLSyntaxError at parse time for unknown fields or
    interval prefixes. This catches user errors before any DB work.

    Results are memoised via ``functools.lru_cache(maxsize=256)`` — typical
    screener usage repeats a small set of queries many times.  Callers
    must treat the returned AST as immutable: do not mutate the node or its
    children, or the cache will return the mutated tree on future calls.
    This is a documented contract — no defensive copy is made.
    """
    return _parse_tql_cached(query)


@functools.lru_cache(maxsize=256)
def _parse_tql_cached(query: str) -> Any:
    """Internal cacheable worker.  Returns a freshly-built AST (no deepcopy)."""
    tokens = tokenize(query.strip())
    ast = Parser(tokens).parse()
    _validate_ast(ast)
    return ast


def _validate_field(field_name: str) -> None:
    """Validate a field name (with optional interval prefix) against _FIELD_MAP.

    Raises TQLSyntaxError for unknown fields or interval prefixes. Matching is
    case-insensitive — "W:RSI" and "w:rsi" are equivalent.
    """
    lowered = field_name.lower()
    if ":" in lowered:
        iv_raw, _ = lowered.split(":", 1)
        if iv_raw not in _VALID_INTERVALS:
            raise TQLSyntaxError(f"Unknown interval prefix {iv_raw!r}")
        # Strip the prefix and validate the bare name
        lowered = lowered.split(":", 1)[1]
    if lowered not in _FIELD_MAP:
        raise TQLSyntaxError(f"Unknown field {field_name!r}")


def _validate_ast(node: Any) -> None:
    """Walk an AST and validate every field reference."""
    if isinstance(node, CompareNode):
        _validate_field(node.field)
    elif isinstance(node, InNode):
        _validate_field(node.field)
    elif isinstance(node, AndNode):
        _validate_ast(node.left)
        _validate_ast(node.right)
    elif isinstance(node, OrNode):
        _validate_ast(node.left)
        _validate_ast(node.right)
    elif isinstance(node, NotNode):
        _validate_ast(node.expr)


# ─── Field resolver ───────────────────────────────────────────────────────────

# Maps lowercase field name → (source, key)
# source: "indicator", "return", "pos52w", "top", "computed"
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "rsi":          ("indicator", "rsi_14"),
    "atr":          ("indicator", "atr_percent"),
    "macd":         ("indicator", "macd"),
    "macdsignal":   ("indicator", "macd_signal"),
    "macdhist":     ("indicator", "macd_histogram"),
    "bbwidth":      ("indicator", "bb_width"),
    "bbsqueeze":    ("indicator", "bb_squeeze"),
    "hv20":         ("indicator", "hv_20"),
    "hv60":         ("indicator", "hv_60"),
    "sharpe60":     ("indicator", "sharpe_60"),
    "sharpe126":    ("indicator", "sharpe_126"),
    "change":       ("top", "change_today"),
    "volume":       ("top", "volume_ratio"),
    "close":        ("top", "close"),
    "sector":       ("top", "sector"),
    "industry":     ("top", "industry"),
    "pe":           ("top", "pe"),
    "momentumscore":("top", "momentum_score"),
    "return1w":     ("return", "1w"),
    "return1m":     ("return", "1m"),
    "return3m":     ("return", "3m"),
    "return6m":     ("return", "6m"),
    "return1y":     ("return", "1y"),
    "from52whigh":  ("pos52w", "pct_from_52w_high"),
    "from52wlow":   ("pos52w", "pct_from_52w_low"),
    "symbol":       ("top", "symbol"),
    "datapoints":   ("top", "data_points"),
}

_VALID_INTERVALS = {"1d", "1h", "w", "m"}
