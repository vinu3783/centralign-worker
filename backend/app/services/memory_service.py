"""Cross-run structured memory (SQLite rows, no embeddings).

- task_outcome: keyed by a goal signature, so the agent can say "I did this
  before on <date>; it changed N records".
- tool_reliability: transient failures per tool, surfaced during planning.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from app.agent.state import StructuredGoal
from app.database.models import AgentMemory
from app.database.session import session_scope


def goal_signature(goal: StructuredGoal) -> str:
    key = {
        "primary": goal.primary_entity,
        "conditions": sorted((c.entity, c.field, c.operator, json.dumps(c.value, sort_keys=True)) for c in goal.conditions),
        "group": goal.group_condition.model_dump() if goal.group_condition else None,
        "actions": sorted((a.type, a.value or "") for a in goal.actions),
    }
    return "goal:" + hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def recall(goal: StructuredGoal, limit: int = 3) -> list[dict[str, Any]]:
    sig = goal_signature(goal)
    with session_scope() as db:
        rows = db.scalars(select(AgentMemory).where(AgentMemory.key == sig)
                          .order_by(AgentMemory.created_at.desc()).limit(limit)).all()
        return [{"run_id": r.run_id, "at": r.created_at.isoformat(), **r.value} for r in rows]


def tool_reliability(tools: list[str]) -> dict[str, int]:
    with session_scope() as db:
        rows = db.scalars(select(AgentMemory).where(AgentMemory.kind == "tool_reliability",
                                                    AgentMemory.key.in_([f"tool:{t}" for t in tools]))).all()
        out: dict[str, int] = {}
        for r in rows:
            out[r.key[5:]] = out.get(r.key[5:], 0) + int(r.value.get("transient_failures", 0))
        return out


def remember_outcome(goal: StructuredGoal, run_id: str, value: dict[str, Any],
                     transient_failures: dict[str, int]) -> None:
    with session_scope() as db:
        db.add(AgentMemory(key=goal_signature(goal), kind="task_outcome", run_id=run_id, value=value))
        for tool, n in transient_failures.items():
            db.add(AgentMemory(key=f"tool:{tool}", kind="tool_reliability", run_id=run_id,
                               value={"transient_failures": n}))
