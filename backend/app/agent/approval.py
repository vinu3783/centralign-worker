"""request_approval / await_approval nodes.

request_approval records the request (DB + event) exactly once; await_approval
pauses the graph with LangGraph's interrupt(). The checkpoint is persisted, so
the run resumes when a human decides via the API, even after a server restart.
"""
from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.agent.runtime import PLURAL, AgentRuntime, updates
from app.agent.state import AgentState, ApprovalInfo, now_iso
from app.services import run_store


def _message(step_desc: str, tool_name: str, risk: str, entity: str | None, preview: list[dict[str, Any]]) -> str:
    to_change = [p for p in preview if not p.get("compliant")]
    skip = len(preview) - len(to_change)
    missing = [p for p in to_change if p.get("exists") is False]
    noun = PLURAL.get(entity, "records")
    msg = (f"I found {len(preview)} {noun} for this step. Running {tool_name} will modify "
           f"{len(to_change)} CRM record(s) — {step_desc.rstrip('.')}. Risk level: {risk.upper()}.")
    if skip:
        msg += f" {skip} already in the desired state will be skipped."
    if missing:
        msg += f" {len(missing)} target(s) could not be found and will likely fail."
    return msg


def request_approval(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    assert s.plan is not None
    step = s.plan.steps[s.current_step]
    sr = s.step_runs[step.id]
    tool = rt.registry.get(step.tool)
    preview = [p for p in sr.preview if not p.get("compliant")] or sr.preview
    message = _message(step.description, tool.name, tool.risk_level.value, tool.entity, sr.preview)
    approval_id = run_store.create_approval(s.run_id, step.id, tool.name, tool.risk_level.value, message, preview)
    info = ApprovalInfo(approval_id=approval_id, step_id=step.id, tool=tool.name, risk_level=tool.risk_level.value,
                        message=message, preview=preview)
    s.approvals.append(info)
    s.approval_required, s.approval_status, s.status = True, "pending", "awaiting_approval"
    s.memory.approvals.append(f"Requested approval for {step.id} ({tool.name})")
    run_store.update_run(s.run_id, status="awaiting_approval")
    rt.emit(s, "approval_required", node="request_approval", status="waiting", step_id=step.id, tool=tool.name,
            risk=tool.risk_level.value, approval_id=approval_id, title="Human approval required", message=message,
            preview=preview)
    rt.audit(s, "request_approval", tool=tool.name, input={"step": step.id, "preview": preview}, status="waiting")
    return updates(s)


def await_approval(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    pending = state.approvals[-1]
    decision = interrupt({"approval_id": pending.approval_id, "step_id": pending.step_id, "message": pending.message})
    s = state.model_copy(deep=True)
    approved = bool(decision.get("approved"))
    info = s.approvals[-1]
    info.status = "approved" if approved else "rejected"
    info.decided_by = decision.get("by") or "operator"
    info.comment = decision.get("comment")
    info.decided_at = now_iso()
    sr = s.step_runs[info.step_id]
    sr.approved = approved
    s.approval_required = False
    s.approval_status = "approved" if approved else "rejected"
    s.memory.approvals.append(f"{info.step_id}: {info.status} by {info.decided_by}")
    rt.emit(s, "approval_decision", node="await_approval", status="success" if approved else "error",
            step_id=info.step_id, approved=approved, by=info.decided_by, comment=info.comment,
            title=f"{'Approved' if approved else 'Rejected'} by {info.decided_by}"
                  + (f": {info.comment}" if info.comment else ""))
    rt.audit(s, "await_approval", input={"approval_id": info.approval_id}, output=decision,
             status="approved" if approved else "rejected")
    if approved:
        s.status = "running"
        run_store.update_run(s.run_id, status="running")
        s.route = "approved"
    else:
        sr.status = "rejected"
        s.status = "rejected"
        s.route = "rejected"
    return updates(s)
