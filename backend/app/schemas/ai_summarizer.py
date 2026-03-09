"""Pydantic schemas for AI summarizer."""

from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Financial statement text to summarize")
    max_tokens: int = Field(default=512, ge=64, le=2048, description="Max tokens in response")


class SummaryResult(BaseModel):
    summary: str = Field(..., description="Generated summary text")
    input_tokens: int = Field(..., description="Number of input tokens")
    output_tokens: int = Field(..., description="Number of output tokens")
    model: str = Field(..., description="Model used for inference")
