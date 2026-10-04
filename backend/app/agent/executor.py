"""select_tool and execute_action nodes.

select_tool walks the plan, resolves step references, previews writes against
ground truth, gates risky steps behind approval, and prepares exactly one
validated tool call. execute_action performs it through the registry.
"""
from __future__ import annotations

from typing import Any

from app.agent.refs import RefError, resolve, resolve_ref
from app.agent.runtime import AgentRuntime, fmt_call, item_args, iterates, ref_scope, updates
from app.agent.state import AgentState, ApprovalInfo, PendingCall, PlanStep, StepRun, ToolCallRecord, now_iso
from app.tools.base import ErrorCode, ToolContext, ToolError, ToolResult
from app.tools.tool_registry import FaultInjector, requires_approval


def _fail_before_call(s: AgentState, rt: AgentRuntime, step: PlanStep, item_index: int | None,
                      error: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """A call that cannot even be attempted (bad reference / invalid args) goes to recovery."""
    s.pending_call = PendingCall(step_id=step.id, item_index=item_index, tool=step.tool, args=args or {})
    s.last_result = ToolResult(success=False, tool=step.tool, error=error, error_code=ErrorCode.VALIDATION,
                               retryable=False)
    rt.emit(s, "tool_call", node="select_tool", status="error", step_id=step.id, tool=step.tool,
            title=f"Cannot call {step.tool}: {error}")
    rt.audit(s, "select_tool", tool=step.tool, input=args, status="failed", error=error)
    s.route = "failure"
    return updates(s)


def finish_step(s: AgentState, rt: AgentRuntime, step: PlanStep, sr: StepRun) -> None:
    if sr.status in ("running", "pending"):
        if sr.items is not None:
            failed = sr.item_status.count("failed")
            sr.status = "completed" if failed == 0 else ("failed" if failed == len(sr.items) else "partial")
        else:
            sr.status = "completed"
    s.completed_steps.append(step.id)
    s.pending_steps = [p for p in s.pending_steps if p != step.id]
    s.current_step += 1
    counts = {k: sr.item_status.count(k) for k in ("succeeded", "compliant", "failed")} if sr.items is not None else {}
    rt.emit(s, "step", node="evaluate_result", step_id=step.id, tool=step.tool,
            status={"completed": "success", "partial": "warning", "failed": "error"}.get(sr.status, "info"),
            title=f"Step {step.id} {sr.status}: {step.description}", counts=counts, notes=sr.notes)


def _preview_writes(s: AgentState, rt: AgentRuntime, step: PlanStep, sr: StepRun) -> None:
    """Read current values of every record the step would modify (from ground truth).
    Records already in the desired state are marked compliant and skipped."""
    tool = rt.registry.get(step.tool)
    sr.preview = []
    for j, args in item_args(s, step, sr):
        row: dict[str, Any] = {"item_index": j, "call": fmt_call(step.tool, args)}
        try:
            target = tool.mutation_target(rt.registry.validate_args(step.tool, args))
        except ToolError as exc:
            row.update(error=exc.message)
            sr.preview.append(row)
            continue
        if target is not None:
            exists, current = rt.reader.read_field(target.entity, target.entity_id, target.field)
            compliant = exists and current == target.desired
            row.update(entity=target.entity, entity_id=target.entity_id, field=target.field,
                       label=rt.reader.label(target.entity, target.entity_id) or f"{target.entity} {target.entity_id}",
                       current=current if exists else None, desired=target.desired, exists=exists, compliant=compliant)
            if compliant and j is not None:
                sr.item_status[j] = "compliant"
        else:
            label = args.get("customer_id")
            row.update(label=(rt.reader.label("customer", label) if isinstance(label, int) else None) or row["call"])
        sr.preview.append(row)
    compliant = [p for p in sr.preview if p.get("compliant")]
    if compliant:
        names = ", ".join(str(p["label"]) for p in compliant)
        sr.notes.append(f"{len(compliant)} record(s) already have {compliant[0]['field']} = "
                        f"{compliant[0]['desired']} and will be skipped: {names}")
        rt.emit(s, "observation", node="select_tool", status="info", step_id=step.id,
                title=f"{len(compliant)} of {len(sr.preview)} target record(s) already in the desired state — skipping them",
                notes=[names])


def select_tool(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    assert s.plan is not None
    steps = s.plan.steps
    while s.current_step < len(steps):
        step = steps[s.current_step]
        sr = s.step_runs.setdefault(step.id, StepRun(step_id=step.id))
        tool = rt.registry.get(step.tool)

        if sr.status == "pending":
            sr.status = "running"
            rt.emit(s, "step", node="select_tool", status="running", step_id=step.id, tool=step.tool,
                    risk=tool.risk_level.value,
                    title=f"Step {s.current_step + 1}/{len(steps)}: {step.description}")

        if iterates(step) and sr.items is None:
            try:
                items = step.items if step.items is not None else resolve_ref(step.for_each, ref_scope(s))
            except RefError as exc:
                return _fail_before_call(s, rt, step, None, str(exc))
            if not isinstance(items, list):
                return _fail_before_call(s, rt, step, None, f"for_each {step.for_each} did not produce a list")
            sr.items, sr.item_status = items, ["pending"] * len(items)
            if not items:
                sr.status = "skipped"
                sr.notes.append("No matching records — nothing to do for this step")
                finish_step(s, rt, step, sr)
                continue

        if tool.kind == "write" and not sr.preview:
            try:
                _preview_writes(s, rt, step, sr)
            except RefError as exc:
                return _fail_before_call(s, rt, step, None, str(exc))
            if sr.items is not None and all(st == "compliant" for st in sr.item_status):
                sr.notes.append("All target records were already compliant; no changes required")
                finish_step(s, rt, step, sr)
                continue

        if tool.kind == "write" and sr.approved is None and requires_approval(tool.risk_level, s.options.approval_threshold):
            ambiguous = bool(s.normalized_goal and s.normalized_goal.ambiguities)
            if s.options.auto_approve and not ambiguous:
                sr.approved = True
                s.approvals.append(ApprovalInfo(step_id=step.id, tool=step.tool, risk_level=tool.risk_level.value,
                                                message="Auto-approved by run policy", status="auto_approved",
                                                decided_by="policy", decided_at=now_iso()))
                rt.emit(s, "approval", node="select_tool", status="info", step_id=step.id, tool=step.tool,
                        title=f"{tool.risk_level.value.upper()}-risk step auto-approved by run policy")
            else:
                if s.options.auto_approve:
                    rt.emit(s, "approval", node="select_tool", status="warning", step_id=step.id, tool=step.tool,
                            title="Auto-approve overridden: the request was ambiguous, so a human must confirm this change")
                s.route = "approval"
                return updates(s)
        elif tool.kind == "write" and sr.approved is None:
            sr.approved = True  # below the approval threshold

        if iterates(step):
            j = next((k for k in range(sr.item_index, len(sr.items or [])) if sr.item_status[k] == "pending"), None)
            if j is None:
                finish_step(s, rt, step, sr)
                continue
            sr.item_index, scope = j, ref_scope(s, (sr.items or [])[j])
        else:
            if sr.output is not None:
                finish_step(s, rt, step, sr)
                continue
            j, scope = None, ref_scope(s)

        try:
            args = resolve(step.args, scope)
        except RefError as exc:
            return _fail_before_call(s, rt, step, j, str(exc))
        try:
            rt.registry.validate_args(step.tool, args)
        except ToolError as exc:
            return _fail_before_call(s, rt, step, j, exc.message, args)
        s.pending_call = PendingCall(step_id=step.id, item_index=j, tool=step.tool, args=args)
        s.route = "execute"
        return updates(s)

    s.pending_call = None
    s.route = "verify"
    return updates(s)


def execute_action(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    pc = s.pending_call
    assert pc is not None
    call_id = f"c{len(s.tool_calls) + 1}"
    title = fmt_call(pc.tool, pc.args)
    rt.emit(s, "tool_call", node="execute_action", status="running", call_id=call_id, step_id=pc.step_id,
            tool=pc.tool, attempt=pc.attempt, item_index=pc.item_index, title=title, input=pc.args)

    injector = FaultInjector(s.options.faults, s.fault_hits)
    ex = rt.registry.execute(pc.tool, pc.args, ToolContext(run_id=s.run_id), injector)
    s.fault_hits = injector.hits
    res = ex.result
    s.tool_calls.append(ToolCallRecord(id=call_id, step_id=pc.step_id, item_index=pc.item_index, tool=pc.tool,
                                       args=pc.args, attempt=pc.attempt, result=res, duration_ms=ex.duration_ms,
                                       injected_fault=ex.injected_fault))
    s.last_result, s.last_call_id = res, call_id
    rt.audit(s, "execute_action", tool=pc.tool, input=pc.args,
             output={"success": res.success, "data": res.data, "metadata": res.metadata},
             status="success" if res.success else "failed",
             error=f"[{res.error_code.value}] {res.error}" if res.error_code else res.error, duration_ms=ex.duration_ms)
    rt.emit(s, "tool_call", node="execute_action", status="success" if res.success else "error", call_id=call_id,
            step_id=pc.step_id, tool=pc.tool, attempt=pc.attempt, item_index=pc.item_index, title=title,
            input=pc.args, output=res.data if res.success else None, metadata=res.metadata,
            error=res.error, error_code=res.error_code.value if res.error_code else None,
            retryable=res.retryable, duration_ms=ex.duration_ms, injected_fault=ex.injected_fault)
    s.route = "observe"
    return updates(s)
