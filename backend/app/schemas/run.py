from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RunSummary(BaseModel):
    id: str
    task_id: str
    goal: str
    status: str
    mode: str
    model: str
    metrics: dict[str, Any]
    verification_passed: bool | None
    started_at: datetime
    finished_at: datetime | None


class RunDetail(RunSummary):
    structured_goal: dict[str, Any] | None
    plan: dict[str, Any] | None
    final_result: dict[str, Any] | None
    error: str | None
    approvals: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    live: dict[str, Any] | None  # snapshot of the agent state (current step, retries, ...)
