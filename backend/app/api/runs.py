from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database.models import Approval, AuditLog, Evidence, Run
from app.database.session import session_scope
from app.schemas.run import RunDetail, RunSummary
from app.services.event_bus import bus, history
from app.services.task_service import get_manager

router = APIRouter(prefix="/api", tags=["runs"])


def _summary(r: Run) -> dict[str, Any]:
    return RunSummary(id=r.id, task_id=r.task_id, goal=r.goal, status=r.status, mode=r.mode, model=r.model,
                      metrics=r.metrics or {}, verification_passed=r.verification_passed, started_at=r.started_at,
                      finished_at=r.finished_at).model_dump(mode="json")


def _live(run_id: str) -> dict[str, Any] | None:
    st = get_manager().state(run_id)
    if st is None:
        return None
    step = st.plan.steps[st.current_step] if st.plan and st.current_step < len(st.plan.steps) else None
    return {
        "status": st.status, "current_step": step.id if step else None,
        "current_tool": st.pending_call.tool if st.pending_call else (step.tool if step else None),
        "completed_steps": st.completed_steps, "pending_steps": st.pending_steps,
        "step_runs": {k: {"status": v.status, "item_status": v.item_status, "notes": v.notes, "preview": v.preview}
                      for k, v in st.step_runs.items()},
        "retry_count": st.retry_count, "tool_calls": len(st.tool_calls),
        "errors": [e.model_dump(mode="json") for e in st.errors],
        "observations": [o.model_dump(mode="json") for o in st.observations],
        "approval_status": st.approval_status, "memory": st.memory.model_dump(mode="json"),
        "verification_results": [v.model_dump(mode="json") for v in st.verification_results],
        "tool_call_log": [c.model_dump(mode="json") for c in st.tool_calls],
    }


@router.get("/runs")
def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as db:
        return [_summary(r) for r in db.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit))]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> dict[str, Any]:
    with session_scope() as db:
        r = db.get(Run, run_id)
        if r is None:
            raise HTTPException(404, "Run not found")
        approvals = [{"id": a.id, "step_id": a.step_id, "tool": a.tool, "risk_level": a.risk_level,
                      "message": a.message, "preview": a.preview, "status": a.status, "decided_by": a.decided_by,
                      "comment": a.comment, "requested_at": a.requested_at.isoformat(),
                      "decided_at": a.decided_at.isoformat() if a.decided_at else None}
                     for a in db.scalars(select(Approval).where(Approval.run_id == run_id).order_by(Approval.id))]
        evidence = [{"id": e.id, "kind": e.kind, "entity": e.entity, "entity_id": e.entity_id, "label": e.label,
                     "field": e.field, "before": e.before, "after": e.after, "verified": e.verified,
                     "details": e.details, "timestamp": e.timestamp.isoformat()}
                    for e in db.scalars(select(Evidence).where(Evidence.run_id == run_id).order_by(Evidence.id))]
        return {**_summary(r), "structured_goal": r.structured_goal, "plan": r.plan, "final_result": r.final_result,
                "error": r.error, "approvals": approvals, "evidence": evidence, "live": _live(run_id)}


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0) -> list[dict[str, Any]]:
    return history(run_id, after)


@router.get("/runs/{run_id}/audit")
def run_audit(run_id: str) -> list[dict[str, Any]]:
    return audit_rows(run_id=run_id, limit=1000)


def audit_rows(run_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as db:
        q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if run_id:
            q = q.where(AuditLog.run_id == run_id)
        return [{"id": a.id, "run_id": a.run_id, "timestamp": a.timestamp.isoformat(), "agent_step": a.agent_step,
                 "tool": a.tool, "input": a.input, "output": a.output, "status": a.status, "error": a.error,
                 "duration_ms": a.duration_ms} for a in db.scalars(q)]


@router.websocket("/runs/{run_id}/ws")
async def run_stream(ws: WebSocket, run_id: str) -> None:
    """Replays the run's events, then streams new ones live."""
    await ws.accept()
    queue = bus.subscribe(run_id)
    last = int(ws.query_params.get("after", 0))
    try:
        for event in await asyncio.to_thread(history, run_id, last):
            await ws.send_json(event)
            last = event["seq"]
        while True:
            event = await queue.get()
            if event["seq"] > last:
                await ws.send_json(event)
                last = event["seq"]
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(run_id, queue)
