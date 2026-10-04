from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["Active", "High Priority", "At Risk", "Inactive"] | None = None
    risk_level: Literal["low", "medium", "high"] | None = None


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Literal["low", "medium", "high"] | None = None
    status: Literal["open", "in_progress", "resolved", "closed"] | None = None


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
