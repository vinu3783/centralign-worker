"""Dependencies injected into graph nodes, plus small helpers shared by them."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.agent.llm import LLMProvider
from app.agent.refs import resolve
from app.agent.state import AgentState, PlanStep, StepRun
from app.config import Settings
from app.services import audit_service
from app.services.event_bus import bus
from app.services.state_reader import StateReader
from app.tools.tool_registry import ToolRegistry

_MISSING = object()


@dataclass
class AgentRuntime:
    registry: ToolRegistry
    llm: LLMProvider
    settings: Settings
    reader: StateReader = field(default_factory=StateReader)
    sleep: Callable[[float], None] = time.sleep

    def emit(self, state: AgentState, type: str, **payload: Any) -> None:
        bus.publish(state.run_id, type, **payload)

    def audit(self, state: AgentState, agent_step: str, **kw: Any) -> None:
        audit_service.record(state.run_id, agent_step, **kw)


def updates(s: AgentState) -> dict[str, Any]:
    """Node return value: every field of the (mutated copy of the) state."""
    return {name: getattr(s, name) for name in AgentState.model_fields}


def ref_scope(s: AgentState, item: Any = _MISSING) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    for sid, sr in s.step_runs.items():
        if sr.output is not None:
            scope[sid] = sr.output
        elif sr.items is not None:
            scope[sid] = {"data": sr.outputs, "metadata": {"count": len(sr.outputs)}}
    if item is not _MISSING:
        scope["item"] = item
    return scope


def iterates(step: PlanStep) -> bool:
    return step.for_each is not None or step.items is not None


def item_args(s: AgentState, step: PlanStep, sr: StepRun) -> Iterator[tuple[int | None, dict[str, Any]]]:
    """Resolved arguments for every call a step makes (one per item, or a single call)."""
    if iterates(step):
        for j, item in enumerate(sr.items or []):
            yield j, resolve(step.args, ref_scope(s, item))
    else:
        yield None, resolve(step.args, ref_scope(s))


def fmt_call(tool: str, args: dict[str, Any]) -> str:
    parts = []
    for k, v in args.items():
        if k in ("reason", "body"):
            continue
        if isinstance(v, list):
            v = f"[{len(v)} items]" if len(v) > 4 or any(isinstance(x, dict) for x in v) else v
        parts.append(f"{k}={v!r}")
    return f"{tool}({', '.join(parts)})"


PLURAL = {"invoice": "invoices", "customer": "customers", "ticket": "tickets", "activity": "activity entries",
          "report": "reports", None: "records"}
