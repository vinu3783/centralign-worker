"""Persistence of run-level records (run row, approvals, evidence)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database.models import Approval, Evidence, Run
from app.database.session import session_scope


def update_run(run_id: str, **fields: Any) -> None:
    with session_scope() as db:
        run = db.get(Run, run_id)
        if run is None:
            return
        for k, v in fields.items():
            setattr(run, k, v.model_dump(mode="json") if hasattr(v, "model_dump") else v)


def create_approval(run_id: str, step_id: str, tool: str, risk: str, message: str,
                    preview: list[dict[str, Any]]) -> int:
    with session_scope() as db:
        appr = Approval(run_id=run_id, step_id=step_id, tool=tool, risk_level=risk, message=message,
                        preview=preview, status="pending")
        db.add(appr)
        db.flush()
        return appr.id


def pending_approval(run_id: str) -> Approval | None:
    with session_scope() as db:
        return db.scalar(select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
                         .order_by(Approval.id.desc()))


def decide_approval(approval_id: int, approved: bool, by: str, comment: str | None) -> None:
    with session_scope() as db:
        appr = db.get(Approval, approval_id)
        if appr is None or appr.status != "pending":
            raise ValueError("Approval is not pending")
        appr.status = "approved" if approved else "rejected"
        appr.decided_by, appr.comment, appr.decided_at = by, comment, datetime.now(timezone.utc)


def save_evidence(run_id: str, items: list[Any]) -> None:
    with session_scope() as db:
        for e in items:
            db.add(Evidence(run_id=run_id, kind=e.kind, entity=e.entity, entity_id=e.entity_id, label=e.label,
                            field=e.field, before=e.before, after=e.after, verified=e.verified,
                            details={**e.details, **({"call_id": e.call_id} if e.call_id else {})}))
