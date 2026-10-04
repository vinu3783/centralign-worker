"""Audit log: every agent step and tool call, with secrets scrubbed and payloads capped."""
from __future__ import annotations

import re
from typing import Any

from app.database.models import AuditLog
from app.database.session import session_scope

_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password|authorization|credential)", re.I)
MAX_LIST = 50


def scrub(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: ("***" if _SECRET_KEY.search(str(k)) else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        items = [scrub(v) for v in value[:MAX_LIST]]
        if len(value) > MAX_LIST:
            items.append(f"... {len(value) - MAX_LIST} more")
        return items
    return value


def record(run_id: str, agent_step: str, *, status: str, tool: str | None = None, input: Any = None,
           output: Any = None, error: str | None = None, duration_ms: float | None = None) -> None:
    with session_scope() as db:
        db.add(AuditLog(
            run_id=run_id, agent_step=agent_step, tool=tool,
            input=scrub(input) if input is not None else None,
            output=scrub(output if isinstance(output, dict) else {"value": output}) if output is not None else None,
            status=status, error=error, duration_ms=duration_ms,
        ))
