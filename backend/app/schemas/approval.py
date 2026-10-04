from __future__ import annotations

from pydantic import BaseModel, Field


class ApprovalDecision(BaseModel):
    by: str = Field("operator", max_length=120)
    comment: str | None = Field(None, max_length=500)
