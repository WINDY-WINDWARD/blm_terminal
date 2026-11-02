"""Pydantic schemas for AI workflows, runs, and custom prompts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ScheduleType = Literal["daily", "weekdays", "weekly", "hourly", "once", "custom"]
PromptMode = Literal["research", "script"]


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    prompt: str = Field(..., min_length=1, max_length=4000)
    schedule_type: ScheduleType
    time_of_day: str | None = None
    days_of_week: list[int] | None = None
    cron: str | None = None
    once_at: datetime | None = None
    symbols: list[str] | None = None
    watchlist_id: int | None = None
    model: str | None = None
    persona: str | None = None
    catch_up_enabled: bool = True
    catch_up_window_hours: int | None = None
    allow_write_tools: bool = False


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    prompt: str | None = Field(None, min_length=1, max_length=4000)
    schedule_type: ScheduleType | None = None
    time_of_day: str | None = None
    days_of_week: list[int] | None = None
    cron: str | None = None
    once_at: datetime | None = None
    symbols: list[str] | None = None
    watchlist_id: int | None = None
    model: str | None = None
    persona: str | None = None
    catch_up_enabled: bool | None = None
    catch_up_window_hours: int | None = None
    allow_write_tools: bool | None = None
    is_enabled: bool | None = None


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    prompt: str
    schedule_type: str
    cron_expression: str
    timezone: str
    time_of_day: str | None = None
    days_of_week: str | None = None
    symbols: list[str] = Field(default_factory=list)
    watchlist_id: int | None = None
    model: str | None = None
    persona: str | None = None
    mode: str
    allow_write_tools: bool
    is_enabled: bool
    catch_up_enabled: bool
    catch_up_window_hours: int
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    schedule_label: str
    created_at: datetime

    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass
        return []


class WorkflowPreviewRequest(BaseModel):
    schedule_type: ScheduleType
    time_of_day: str | None = None
    days_of_week: list[int] | None = None
    cron: str | None = None
    once_at: datetime | None = None
    timezone: str = "Asia/Kolkata"


class WorkflowPreviewOut(BaseModel):
    cron_expression: str
    schedule_label: str
    next_runs: list[datetime]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    trigger: str
    status: str
    skip_reason: str | None = None
    scheduled_for: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    session_id: int | None = None
    output_summary: str | None = None
    error: str | None = None
    attempt: int
    is_read: bool
    is_silent: bool
    name_snapshot: str | None = None
    created_at: datetime


class PromptCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    tag: str = Field(..., min_length=1, max_length=48)
    description: str | None = Field(None, max_length=240)
    prompt: str = Field(..., min_length=1, max_length=4000)
    icon: str | None = Field(None, max_length=8)
    mode: PromptMode = "research"


class PromptUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=80)
    tag: str | None = Field(None, min_length=1, max_length=48)
    description: str | None = Field(None, max_length=240)
    prompt: str | None = Field(None, min_length=1, max_length=4000)
    icon: str | None = Field(None, max_length=8)
    mode: PromptMode | None = None
    sort_order: int | None = None


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    tag: str
    description: str | None = None
    prompt: str
    icon: str | None = None
    mode: str
    sort_order: int
    use_count: int
    last_used_at: datetime | None = None
    created_at: datetime


class WorkflowSummaryOut(BaseModel):
    armed: int
    unread: int
    running: int
    next_run_at: datetime | None = None
    server_now: datetime
