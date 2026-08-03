"""Pydantic schemas for layout endpoints."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LayoutCreateOrUpdate(BaseModel):
    """Input schema for creating or updating a layout."""

    name: str = Field(..., min_length=1, max_length=64)
    active_panels: dict[str, str] = Field(..., alias="activePanels")
    panel_count: int = Field(..., alias="panelCount")
    merged_groups: dict[str, Any] = Field(default_factory=dict, alias="mergedGroups")
    saved_at: int = Field(..., alias="savedAt")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("name must be a non-empty string")
        return v.strip().lower()

    @field_validator("panel_count", mode="before")
    @classmethod
    def validate_panel_count(cls, v: object) -> int:
        if v not in (2, 4, 6, 8):
            raise ValueError("panelCount must be 2, 4, 6, or 8")
        return int(v)


class LayoutRename(BaseModel):
    """Input schema for renaming a layout."""

    new_name: str = Field(..., alias="newName", min_length=1, max_length=64)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("new_name", mode="before")
    @classmethod
    def normalize_name(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("newName must be a non-empty string")
        return v.strip().lower()


class LayoutOut(BaseModel):
    """Output schema for a layout."""

    name: str
    active_panels: dict[str, str] = Field(..., alias="activePanels")
    panel_count: int = Field(..., alias="panelCount")
    merged_groups: dict[str, Any] = Field(default_factory=dict, alias="mergedGroups")
    saved_at: int = Field(..., alias="savedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LayoutTombstoneOut(BaseModel):
    """Output schema for a layout tombstone."""

    name: str
    deleted_at: int = Field(..., alias="deletedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LayoutSyncResponse(BaseModel):
    """Output schema for bulk sync response."""

    layouts: list[LayoutOut]
    tombstones: list[LayoutTombstoneOut]
