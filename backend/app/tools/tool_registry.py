"""Allowlisted tool registry: the ONLY way the agent can touch the environment."""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.tools.base import ErrorCode, RiskLevel, Tool, ToolContext, ToolError, ToolResult
from app.tools.browser_tools import BROWSER_TOOLS
from app.tools.compute_tools import COMPUTE_TOOLS
from app.tools.crm_tools import CRM_TOOLS
from app.tools.file_tools import FILE_TOOLS

log = logging.getLogger(__name__)


class FaultSpec(BaseModel):
    """A controlled failure injected into the simulated environment (demo/testing).

    mode="error": the call fails with the given error and nothing is written.
    mode="lost_write": the call *reports success* but the write is not persisted
    (only independent verification can catch this).
    """

    tool: str
    mode: Literal["error", "lost_write"] = "error"
    error: str = "Temporary database timeout"
    error_code: ErrorCode = ErrorCode.TIMEOUT
    times: int = Field(1, ge=1, le=100)
    match: dict[str, Any] | None = None  # only calls whose args contain these values


class FaultInjector:
    def __init__(self, specs: list[FaultSpec], hits: dict[str, int] | None = None):
        self.specs = specs
        self.hits: dict[str, int] = dict(hits or {})

    def take(self, tool: str, args: dict[str, Any]) -> FaultSpec | None:
        for i, spec in enumerate(self.specs):
            if spec.tool != tool:
                continue
            if spec.match and any(args.get(k) != v for k, v in spec.match.items()):
                continue
            used = self.hits.get(str(i), 0)
            if used < spec.times:
                self.hits[str(i)] = used + 1
                return spec
        return None


class Execution(BaseModel):
    result: ToolResult
    duration_ms: float
    injected_fault: str | None = None


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(ErrorCode.UNKNOWN_TOOL, f"Tool '{name}' is not in the allowlist", retryable=False)
        return self._tools[name]

    def catalog(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def validate_args(self, name: str, args: dict[str, Any]) -> BaseModel:
        """Raises ToolError(VALIDATION) with a readable message."""
        tool = self.get(name)
        try:
            return tool.input_model.model_validate(args)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors()[:5])
            raise ToolError(ErrorCode.VALIDATION, f"Invalid arguments for {name}: {problems}", retryable=False) from exc

    def execute(self, name: str, args: dict[str, Any], ctx: ToolContext,
                faults: FaultInjector | None = None) -> Execution:
        start = time.perf_counter()
        injected: str | None = None
        try:
            tool = self.get(name)
            parsed = self.validate_args(name, args)
            fault = faults.take(name, args) if faults else None
            if fault and fault.mode == "error":
                injected = f"{fault.error_code.value}: {fault.error}"
                raise ToolError(fault.error_code, fault.error)
            if fault and fault.mode == "lost_write":
                injected = "lost_write"
                ctx.lose_write = True
            result = tool.execute(parsed, ctx)
        except ToolError as exc:
            result = ToolResult(success=False, tool=name, error=exc.message, error_code=exc.code,
                                retryable=exc.retryable)
        except OperationalError as exc:  # e.g. sqlite "database is locked"
            result = ToolResult(success=False, tool=name, error=f"Database unavailable: {exc.orig}",
                                error_code=ErrorCode.TIMEOUT, retryable=True)
        except Exception as exc:  # never let a tool crash the agent loop
            log.exception("Tool %s crashed", name)
            result = ToolResult(success=False, tool=name, error=f"Internal tool error: {exc}",
                                error_code=ErrorCode.INTERNAL, retryable=False)
        finally:
            ctx.lose_write = False
        return Execution(result=result, duration_ms=round((time.perf_counter() - start) * 1000, 1),
                         injected_fault=injected)


def requires_approval(risk: RiskLevel, threshold: str) -> bool:
    if threshold == "none":
        return False
    return risk.rank >= RiskLevel(threshold).rank


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        tools = CRM_TOOLS + COMPUTE_TOOLS + FILE_TOOLS
        if get_settings().browser_tools_enabled:
            tools = tools + BROWSER_TOOLS
        _registry = ToolRegistry(tools)
    return _registry
