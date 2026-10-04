"""Tool contracts shared by every tool family (API/DB, browser, file, compute)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"low": 1, "medium": 2, "high": 3}[self.value]


class ErrorCode(str, Enum):
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


RETRYABLE_CODES = {ErrorCode.TIMEOUT, ErrorCode.RATE_LIMITED, ErrorCode.UNAVAILABLE}

ToolKind = Literal["read", "compute", "write"]
ToolChannel = Literal["api", "browser", "file", "compute"]


class StrictInput(BaseModel):
    """Base for tool inputs: unknown arguments are rejected, never ignored."""

    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    success: bool
    tool: str
    data: Any = None
    metadata: dict[str, Any] = {}
    error: str | None = None
    error_code: ErrorCode | None = None
    retryable: bool = False


class ToolError(Exception):
    def __init__(self, code: ErrorCode, message: str, retryable: bool | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable


class MutationTarget(BaseModel):
    """What a write tool intends to change; used for approval previews and verification."""

    entity: Literal["customer", "ticket"]
    entity_id: int
    field: str
    desired: Any


@dataclass
class ToolContext:
    run_id: str | None = None
    actor: str = "CentrAlign Worker"
    settings: Settings = field(default_factory=get_settings)
    # Set by the fault injector: the write "succeeds" but is silently not persisted.
    lose_write: bool = False


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[StrictInput]]
    risk_level: ClassVar[RiskLevel] = RiskLevel.LOW
    kind: ClassVar[ToolKind] = "read"
    channel: ClassVar[ToolChannel] = "api"
    entity: ClassVar[str | None] = None
    # Equivalent tool to try if this one fails non-retryably (e.g. browser -> API).
    fallback_tool: ClassVar[str | None] = None
    # Maps input arg -> (record field, operator); lets the verifier independently
    # re-check every returned record against the filters that produced it.
    filter_semantics: ClassVar[dict[str, tuple[str, str]]] = {}

    @abstractmethod
    def execute(self, args: Any, ctx: ToolContext) -> ToolResult: ...

    def mutation_target(self, args: Any) -> MutationTarget | None:
        return None

    def ok(self, data: Any, **metadata: Any) -> ToolResult:
        if isinstance(data, list) and "count" not in metadata:
            metadata["count"] = len(data)
        return ToolResult(success=True, tool=self.name, data=data, metadata=metadata)

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "risk_level": self.risk_level.value,
            "kind": self.kind,
            "channel": self.channel,
            "entity": self.entity,
            "fallback_tool": self.fallback_tool,
        }
