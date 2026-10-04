from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.database.models import Approval
from app.database.session import session_scope
from app.schemas.approval import ApprovalDecision
from app.services.task_service import get_manager

router = APIRouter(prefix="/api", tags=["approvals"])


def _decide(run_id: str, approved: bool, body: ApprovalDecision) -> dict[str, Any]:
    try:
        get_manager().decide(run_id, approved, body.by, body.comment)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id, "approved": approved}


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, body: ApprovalDecision | None = None) -> dict[str, Any]:
    return _decide(run_id, True, body or ApprovalDecision())


@router.post("/runs/{run_id}/reject")
def reject(run_id: str, body: ApprovalDecision | None = None) -> dict[str, Any]:
    return _decide(run_id, False, body or ApprovalDecision())


@router.get("/approvals")
def list_approvals(status: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as db:
        q = select(Approval).order_by(Approval.id.desc()).limit(100)
        if status:
            q = q.where(Approval.status == status)
        return [{"id": a.id, "run_id": a.run_id, "step_id": a.step_id, "tool": a.tool, "risk_level": a.risk_level,
                 "message": a.message, "status": a.status, "requested_at": a.requested_at.isoformat()}
                for a in db.scalars(q)]
