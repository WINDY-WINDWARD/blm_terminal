"""Pydantic schemas for AI summarizer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Financial statement text to summarize")
    max_tokens: int = Field(default=512, ge=64, le=2048, description="Max tokens in response")


class AlertSummaryItem(BaseModel):
    id: int | None = None
    trigger_type: str = Field(..., description="Alert trigger category (e.g. volume_surge, rsi_overbought)")
    message: str = Field(..., description="Alert description text")
    triggered_at: str | None = Field(default=None, description="ISO timestamp of trigger")
    triggered_date: str | None = Field(default=None, description="Date of trigger")


class AlertSummarizeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, description="Stock ticker symbol")
    alerts: list[AlertSummaryItem] = Field(..., min_length=1, description="List of alerts to summarize")
    max_tokens: int = Field(default=2048, ge=64, le=4096, description="Max tokens in response")


class SummaryResult(BaseModel):
    summary: str = Field(..., description="Generated summary text")
    input_tokens: int = Field(..., description="Number of input tokens")
    output_tokens: int = Field(..., description="Number of output tokens")
    model: str = Field(..., description="Model used for inference")


AlertBias = Literal["bullish", "bearish", "mixed", "neutral"]


class AlertDigestResult(SummaryResult):
    """Structured, decision-ready alert digest."""

    model_config = ConfigDict(extra="forbid")

    bias: AlertBias = Field(..., description="Near-term directional bias")
    trigger: str = Field(..., description="Condition that confirms the setup")
    invalidation: str = Field(..., description="Condition that invalidates the setup")
    risk: str = Field(..., description="Primary risk or conflicting signal")

    @field_validator("bias", mode="before")
    @classmethod
    def normalize_bias(cls, value: object) -> str:
        return str(value).strip().lower()

    @field_validator("summary", "trigger", "invalidation", "risk")
    @classmethod
    def normalize_digest_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Digest fields cannot be empty")
        return normalized
