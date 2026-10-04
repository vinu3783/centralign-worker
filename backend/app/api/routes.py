"""System endpoints + router aggregation."""
from __future__ import annotations

import re
from pathlib import Path
from statistics import mean
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api import approvals, crm, runs, tasks
from app.config import get_settings
from app.database.models import Approval, Customer, Invoice, Run, SupportTicket
from app.database.seed import reseed
from app.database.session import session_scope
from app.services.task_service import TERMINAL, get_manager
from app.tools.tool_registry import get_registry

system = APIRouter(prefix="/api", tags=["system"])


@system.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@system.get("/system")
def system_info() -> dict[str, Any]:
    s, m = get_settings(), get_manager()
    return {"mode": m.mode, "model": m.model_label, "approval_threshold": s.approval_threshold,
            "max_retries": s.max_retries, "browser_tools_enabled": s.browser_tools_enabled,
            "frontend_url": s.frontend_url, "tools": len(get_registry().names()),
            "database": s.database_url.split(":")[0]}


@system.get("/tools")
def tools() -> list[dict[str, Any]]:
    return get_registry().catalog()


@system.get("/stats")
def stats() -> dict[str, Any]:
    with session_scope() as db:
        all_runs = db.scalars(select(Run)).all()
        finished = [r for r in all_runs if r.status in TERMINAL]
        completed = [r for r in finished if r.status == "completed"]
        failed = [r for r in finished if r.status in ("failed", "needs_attention")]
        durations = [r.metrics.get("duration_ms", 0) - r.metrics.get("approval_wait_ms", 0)
                     for r in finished if r.metrics]
        recent = db.scalars(select(Run).order_by(Run.started_at.desc()).limit(10)).all()
        return {
            "tasks_completed": len(completed),
            "tasks_failed": len(failed),
            "runs_total": len(all_runs),
            "avg_execution_ms": round(mean(durations)) if durations else None,
            "success_rate": round(len(completed) / len(finished), 3) if finished else None,
            "human_approvals": db.scalar(select(func.count()).select_from(Approval)
                                         .where(Approval.status.in_(["approved", "rejected"]))),
            "pending_approvals": db.scalar(select(func.count()).select_from(Approval).where(Approval.status == "pending")),
            "recovered_failures": sum(r.metrics.get("recovered_failures", 0) for r in finished if r.metrics),
            "crm": {
                "customers": db.scalar(select(func.count()).select_from(Customer)),
                "high_priority": db.scalar(select(func.count()).select_from(Customer).where(Customer.status == "High Priority")),
                "at_risk": db.scalar(select(func.count()).select_from(Customer).where(Customer.status == "At Risk")),
                "unpaid_amount": db.scalar(select(func.coalesce(func.sum(Invoice.amount), 0)).where(Invoice.status != "paid")),
                "overdue_invoices": db.scalar(select(func.count()).select_from(Invoice).where(Invoice.status == "overdue")),
                "open_tickets": db.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "open")),
            },
            "recent_runs": [runs._summary(r) for r in recent],
        }


@system.get("/audit")
def audit(run_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return runs.audit_rows(run_id, min(limit, 1000))


@system.post("/admin/reset")
def reset_crm() -> dict[str, str]:
    """Restore the CRM seed data (run history is kept)."""
    with session_scope() as db:
        busy = db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(["running", "verifying"])))
        if busy:
            raise HTTPException(409, "A run is executing; wait for it to finish")
        reseed(db)
    return {"status": "reset"}


@system.get("/files/{kind}/{name}")
def get_file(kind: str, name: str) -> FileResponse:
    if kind not in ("reports", "screenshots") or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name) or ".." in name:
        raise HTTPException(404)
    path = (Path(get_settings().data_dir) / kind / name).resolve()
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


ROUTERS = [system, crm.router, tasks.router, runs.router, approvals.router]
