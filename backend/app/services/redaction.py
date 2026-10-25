"""Single source of truth for redacting secrets out of logs, errors and diagnostics.

Three narrow implementations used to live in ``oauth_session_manager``,
``ai_picks_worker`` and ``proxy_supervisor``. They drifted apart, so a rule
added to one path silently did not protect the others. Everything that needs to
hide a credential now calls into this module, and no redaction pattern is
allowed anywhere else.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["SENSITIVE_FIELD_NAMES", "redact_text", "redact_mapping"]

REDACTED = "[REDACTED]"

# Field names whose *values* must never be logged. Compared lowercased.
SENSITIVE_FIELD_NAMES = {
    "secret-key",
    "secret_key",
    "management_key",
    "api-key",
    "client_key",
    "api-keys",
    "api_keys",
    "authorization",
    "x-management-key",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
}

_HEADER_KEYS = ("headers", "header")

# Query parameter values that carry credentials.
_QUERY_SECRETS = re.compile(
    r"(?i)([?&](?:token|access_token|refresh_token|key|api_key|secret|client_secret|password)=)[^\s&]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[\w.\-]+")
_SK_KEY = re.compile(r"(?i)\bsk-[a-zA-Z0-9_\-]{8,}")
_CLIENT_SECRET = re.compile(r"(?i)\bclient_secret=[^\s&]+")
_PASSWORD = re.compile(r"(?i)\bpassword=[^\s&]+")
_SENTINEL_PREFIX = re.compile(r"(?i)SENTINEL[_\w]*SECRET[_\w]*")
_SENTINEL_SUFFIX = re.compile(r"(?i)SECRET[_\w]*SENTINEL[_\w]*")
_QUERY_TAIL = re.compile(r"([?&])[^\s]+")


def redact_text(
    value: str | None,
    *,
    limit: int | None = None,
    default: str = "",
    strip_query: bool = False,
) -> str:
    """Mask credentials in free-form text.

    ``strip_query`` removes the whole query string (used for OAuth errors where
    the callback URL itself carries the code). ``limit`` truncates the result
    with an ellipsis; ``default`` is returned for empty input.
    """
    if not value:
        return default

    text = str(value)
    if strip_query:
        text = _QUERY_TAIL.sub("", text)

    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SK_KEY.sub("sk-[REDACTED]", text)
    text = _CLIENT_SECRET.sub("client_secret=[REDACTED]", text)
    text = _PASSWORD.sub("password=[REDACTED]", text)
    text = _QUERY_SECRETS.sub(r"\1[REDACTED]", text)
    text = _SENTINEL_PREFIX.sub("[REDACTED_SENTINEL]", text)
    text = _SENTINEL_SUFFIX.sub("[REDACTED_SENTINEL]", text)

    if limit is not None and len(text) > limit:
        text = text[:limit] + "..."

    return text.strip()


def redact_mapping(value: Any) -> Any:
    """Recursively replace credential values in nested dicts and lists."""
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _HEADER_KEYS and isinstance(item, dict):
                out[key] = {name: REDACTED for name in item}
            elif str(key).lower() in SENSITIVE_FIELD_NAMES:
                out[key] = REDACTED
            else:
                out[key] = redact_mapping(item)
        return out
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return value
