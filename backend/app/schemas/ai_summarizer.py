"""Pydantic schemas for AI summarizer."""

from pydantic import BaseModel, Field


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
    max_tokens: int = Field(default=350, ge=64, le=1024, description="Max tokens in response")


class SummaryResult(BaseModel):
    summary: str = Field(..., description="Generated summary text")
    input_tokens: int = Field(..., description="Number of input tokens")
    output_tokens: int = Field(..., description="Number of output tokens")
    model: str = Field(..., description="Model used for inference")
