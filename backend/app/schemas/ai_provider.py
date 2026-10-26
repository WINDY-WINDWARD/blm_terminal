"""Pydantic schemas for AI provider routes, credentials, and settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

VALID_ROUTING_STRATEGIES = {"fill-first", "round-robin", "priority"}


class RouteSettingsUpdate(BaseModel):
    strategy: str | None = None
    session_affinity: bool | None = None
    session_affinity_ttl: str | None = None
    request_retry: int | None = Field(default=None, ge=0, le=10)
    max_retry_credentials: int | None = Field(default=None, ge=0, le=20)
    max_retry_interval: int | None = Field(default=None, ge=0, le=300)

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        if v is not None:
            clean = v.strip().lower()
            if clean not in VALID_ROUTING_STRATEGIES:
                raise ValueError(
                    f"Invalid routing strategy '{v}'. Must be one of: {sorted(VALID_ROUTING_STRATEGIES)}"
                )
            return clean
        return None


class EndpointKeyInput(BaseModel):
    api_key: str
    label: str | None = None
    priority: int = 1
    weight: int = 1


class EndpointKeyUpdate(BaseModel):
    priority: int | None = None
    weight: int | None = None
    enabled: bool | None = None
    status: str | None = None


class CreateEndpointRequest(BaseModel):
    display_label: str
    base_url: str
    headers: dict[str, str] | None = None
    models: list[str] | None = None
    keys: list[EndpointKeyInput] | None = None


class UpdateEndpointRequest(BaseModel):
    display_label: str | None = None
    base_url: str | None = None
    headers: dict[str, str] | None = None
    models: list[str] | None = None
    enabled: bool | None = None


class RouteEnabledUpdate(BaseModel):
    enabled: bool


class AccountPatchRequest(BaseModel):
    priority: int | None = None
    weight: int | None = None
    enabled: bool | None = None
    status: str | None = None


class OAuthStartRequest(BaseModel):
    provider: str
    flow: str | None = None  # "browser" only; legacy "device" rejected with 400
    replace_account_id: str | None = None


class OAuthCancelRequest(BaseModel):
    state: str


class OAuthCallbackRequest(BaseModel):
    state: str
    code: str | None = None
    redirect_url: str | None = None


class ModelPreviewRequest(BaseModel):
    base_url: str
    headers: dict[str, str] | None = None
    api_key: str | None = None


class CredentialSummary(BaseModel):
    id: str
    route_id: str
    kind: str
    masked_identity: str
    priority: int = 1
    weight: int = 1
    enabled: bool = True
    status: str = "active"
    cooldown: datetime | None = None
    last_redacted_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RouteSummary(BaseModel):
    id: str
    kind: str  # "oauth" | "endpoint" | "direct"
    provider: str
    display_label: str
    proxy_prefix: str | None = None
    enabled: bool = True
    is_active: bool = False
    health: dict[str, Any] = Field(default_factory=dict)
    accounts: list[CredentialSummary] = Field(default_factory=list)
    keys: list[CredentialSummary] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    models: list[str] = Field(default_factory=list)
    recovery_state: str | None = None


class RoutesListResponse(BaseModel):
    routes: list[RouteSummary]
    active_route_id: str
    proxy_status: dict[str, Any]
    vault_state: str
    recovery_state: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
