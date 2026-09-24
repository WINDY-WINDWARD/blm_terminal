"""Pydantic v2 schemas for BLM Script Lab (spec docs/specs/chart-scripts-v1.md)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SPEC_VERSION = 1
MAX_CODE_BYTES = 64 * 1024
MAX_PARAMS = 24
MAX_OUTPUTS = 8

PARAM_TYPES = ("int", "number", "bool", "select", "color", "source")
SOURCE_VALUES = ("open", "high", "low", "close", "hlc3", "hl2", "ohlc4", "volume")
OUTPUT_KINDS = ("line", "histogram", "markers", "priceline", "band")
# Manifest keys reserved for spec v2 — rejected with "requires spec v2".
V2_MANIFEST_KEYS = ("drawings", "alerts", "strategy", "timeframe", "symbol")
# Output kinds reserved for spec v2.
V2_OUTPUT_KINDS = ("drawing", "alert", "strategy")

_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEADER_RE = re.compile(r"//\s*@blm-script\s+(\{.*\})")


class ScriptParam(BaseModel):
    key: str
    label: str = ""
    type: Literal["int", "number", "bool", "select", "color", "source"]
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None

    @field_validator("key")
    @classmethod
    def _key_ident(cls, v: str) -> str:
        if not _IDENT_RE.match(v):
            raise ValueError(f"param key {v!r} must be a valid JS identifier")
        return v

    @model_validator(mode="after")
    def _default_matches_type(self) -> "ScriptParam":
        t = self.type
        d = self.default
        if t == "int":
            if isinstance(d, bool) or not isinstance(d, int):
                raise ValueError(f"int param {self.key!r} default must be an integer")
            self._check_range(float(d))
        elif t == "number":
            if isinstance(d, bool) or not isinstance(d, (int, float)):
                raise ValueError(f"number param {self.key!r} default must be numeric")
            self._check_range(float(d))
        elif t == "bool":
            if not isinstance(d, bool):
                raise ValueError(f"bool param {self.key!r} default must be true/false")
        elif t == "select":
            if not self.options or len(self.options) < 2:
                raise ValueError(f"select param {self.key!r} needs ≥2 options")
            if d not in self.options:
                raise ValueError(f"select param {self.key!r} default must be one of options")
        elif t == "color":
            if not isinstance(d, str) or not _HEX_RE.match(d):
                raise ValueError(f"color param {self.key!r} default must be #rrggbb")
        elif t == "source":
            if d not in SOURCE_VALUES:
                raise ValueError(f"source param {self.key!r} default must be one of {SOURCE_VALUES}")
        return self

    def _check_range(self, d: float) -> None:
        if self.min is not None and d < self.min:
            raise ValueError(f"param {self.key!r} default below min")
        if self.max is not None and d > self.max:
            raise ValueError(f"param {self.key!r} default above max")


class ScriptOutput(BaseModel):
    id: str
    kind: Literal["line", "histogram", "markers", "priceline", "band"]
    overlay: bool = True
    pane: str | None = None
    upper: str | None = None
    lower: str | None = None
    color: str | None = None

    @field_validator("id")
    @classmethod
    def _id_ident(cls, v: str) -> str:
        if not _IDENT_RE.match(v):
            raise ValueError(f"output id {v!r} must be a valid JS identifier")
        return v

    @model_validator(mode="after")
    def _band_refs(self) -> "ScriptOutput":
        if self.kind == "band" and (not self.upper or not self.lower):
            raise ValueError("band output needs upper + lower line ids")
        return self


class ScriptManifest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    version: int
    description: str = Field(default="", max_length=280)
    params: list[ScriptParam] = Field(default_factory=list)
    outputs: list[ScriptOutput] = Field(min_length=1, max_length=MAX_OUTPUTS)
    needs_fundamentals: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("version")
    @classmethod
    def _version_is_v1(cls, v: int) -> int:
        if v != SPEC_VERSION:
            raise ValueError(f"spec version {v} unsupported — requires spec v2")
        return v

    @model_validator(mode="after")
    def _cross_refs(self) -> "ScriptManifest":
        keys = [p.key for p in self.params]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate param keys")
        ids = [o.id for o in self.outputs]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate output ids")
        line_ids = {o.id for o in self.outputs if o.kind == "line"}
        for o in self.outputs:
            if o.kind == "band" and (o.upper not in line_ids or o.lower not in line_ids):
                raise ValueError(f"band {o.id!r} must reference two line outputs of this script")
        return self


def extract_manifest_header(code: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return (header_dict, error). Error is None on success."""
    for line in code.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            try:
                return json.loads(m.group(1)), None
            except json.JSONDecodeError as exc:
                return None, f"E_MANIFEST_JSON: header is not valid JSON ({exc})"
    return None, "E_MANIFEST_JSON: missing // @blm-script {...} header"


def static_code_checks(code: str, manifest: ScriptManifest) -> list[str]:
    """Static (no-execution) code checks. Returns list of E_* error strings."""
    errors: list[str] = []
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        errors.append("E_LIMIT: code exceeds 64KB")
    if not re.search(r"\bfunction\s+calculate\s*\(\s*ctx\s*\)", code):
        errors.append("E_STATIC: top-level function calculate(ctx) not found")
    for banned in (r"\basync\b", r"\bawait\b", r"\bimport\b", r"\brequire\s*\(",
                   r"\bclass\b", r"\bgenerator\b", r"function\s*\*"):
        if re.search(banned, code):
            errors.append(f"E_STATIC: forbidden construct ({banned.strip(chr(92)+'b')})")
            break
    for p in manifest.params:
        if not re.search(r"\bparams\s*\.\s*" + re.escape(p.key) + r"\b"
                         r"|\bparams\s*\[\s*['\"]" + re.escape(p.key) + r"['\"]\s*\]", code):
            errors.append(f"E_PARAM: param {p.key!r} never referenced in code")
    return errors


def validate_script(code: str) -> tuple[ScriptManifest | None, list[str]]:
    """Full backend validation: header JSON + manifest schema + static checks.

    Returns (manifest_or_None, errors). The backend never executes JS.
    """
    header, err = extract_manifest_header(code)
    if err:
        return None, [err]
    assert header is not None
    for k in V2_MANIFEST_KEYS:
        if k in header:
            return None, [f"E_V2_KIND: {k!r} requires spec v2"]
    for o in header.get("outputs", []) if isinstance(header.get("outputs"), list) else []:
        if isinstance(o, dict) and o.get("kind") in V2_OUTPUT_KINDS:
            return None, [f"E_V2_KIND: output kind {o.get('kind')!r} requires spec v2"]
    try:
        manifest = ScriptManifest.model_validate(header)
    except Exception as exc:
        return None, [f"E_MANIFEST_SCHEMA: {exc}"]
    if len(manifest.params) > MAX_PARAMS:
        return None, ["E_MANIFEST_SCHEMA: more than 24 params"]
    return manifest, static_code_checks(code, manifest)


# --- API shapes -------------------------------------------------------------


class ScriptSummaryOut(BaseModel):
    id: int
    name: str
    description: str = ""
    is_builtin: bool = False
    head_rev_no: int | None = None
    updated_at: datetime | None = None


class ScriptRevisionOut(BaseModel):
    rev_no: int
    manifest: dict[str, Any]
    code: str
    note: str = ""
    chat_session_id: int | None = None
    created_at: datetime | None = None


class ScriptDetailOut(BaseModel):
    id: int
    name: str
    description: str = ""
    is_builtin: bool = False
    head_rev_no: int | None = None
    head: ScriptRevisionOut | None = None
    history: list[ScriptRevisionOut] = Field(default_factory=list)


class ScriptCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=280)
    code: str = Field(min_length=1)
    note: str = Field(default="", max_length=280)
    chat_session_id: int | None = None


class ScriptReviseIn(BaseModel):
    code: str = Field(min_length=1)
    note: str = Field(default="", max_length=280)
    chat_session_id: int | None = None


class ScriptRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ScriptRollbackIn(BaseModel):
    rev_no: int = Field(ge=1)


class ChartStateSetIn(BaseModel):
    script_id: int
    enabled: bool = True
    param_values: dict[str, Any] = Field(default_factory=dict)


class ChartStateOut(BaseModel):
    script_id: int
    enabled: bool
    param_values: dict[str, Any]
    name: str = ""
    head_rev_no: int | None = None


class ScriptImportIn(BaseModel):
    payload: dict[str, Any]  # export envelope, validated below


class ValidateIn(BaseModel):
    code: str = Field(min_length=1)


class ValidateOut(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    name: str | None = None
    outputs: list[str] = Field(default_factory=list)
    params: list[str] = Field(default_factory=list)
