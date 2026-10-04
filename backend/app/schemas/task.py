from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.tools.tool_registry import FaultSpec


class TaskOptionsIn(BaseModel):
    auto_approve: bool | None = None
    approval_threshold: Literal["none", "low", "medium", "high"] | None = None
    faults: list[FaultSpec] | None = None
    max_retries: int | None = Field(None, ge=0, le=5)
    scenario: str | None = None


class TaskCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)
    options: TaskOptionsIn = Field(default_factory=TaskOptionsIn)
    run: bool = Field(False, description="Start a run immediately")


class TaskOut(BaseModel):
    id: str
    goal: str
    options: dict[str, Any]
    created_at: datetime
    run_id: str | None = None


class DemoRunIn(BaseModel):
    scenario: str = "standard"
    auto_approve: bool = False
