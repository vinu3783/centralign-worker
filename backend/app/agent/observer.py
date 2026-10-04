"""observe_result and evaluate_result nodes.

observe: turn a raw tool result into an Observation (expected vs actual,
discrepancies, memory updates). evaluate: decide whether the call succeeded and
commit its output, or hand off to recovery.
"""
from __future__ import annotations

from typing import Any

from app.agent.executor import finish_step
from app.agent.refs import RefError, parse_ref, resolve_ref
from app.agent.runtime import PLURAL, AgentRuntime, ref_scope, updates
from app.agent.state import AgentState, EvidenceItem, Observation, PlanStep
from app.tools.base import ErrorCode


def _step(s: AgentState, step_id: str) -> PlanStep:
    assert s.plan is not None
    return next(st for st in s.plan.steps if st.id == step_id)


def _unique_discrepancies(s: AgentState, step: PlanStep) -> list[str]:
    """Explain when N source records collapse to fewer distinct targets."""
    notes = []
    for value in step.args.values():
        if isinstance(value, str) and value.endswith("|unique"):
            try:
                raw = resolve_ref(value[:-7], ref_scope(s))
                distinct = resolve_ref(value, ref_scope(s))
            except RefError:
                continue
            if isinstance(raw, list) and len(distinct) < len(raw):
                src = parse_ref(value)[0]
                src_tool = _step(s, src).tool if src in s.step_runs else "previous step"
                notes.append(f"{len(raw)} records from {src} ({src_tool}) map to {len(distinct)} distinct "
                             f"{value.split('.')[-1].split('|')[0].replace('_id', '')}s — some share the same one; "
                             f"continuing with {len(distinct)}")
    return notes


def observe_result(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    pc, res = s.pending_call, s.last_result
    assert pc is not None and res is not None
    step = _step(s, pc.step_id)
    tool = rt.registry.get(pc.tool)
    obs = Observation(step_id=step.id, call_id=s.last_call_id, summary="")

    if not res.success:
        kind = "retryable" if res.retryable else "not retryable"
        obs.ok, obs.summary = False, f"{pc.tool} failed: [{res.error_code.value if res.error_code else '?'}] {res.error} ({kind})"
        s.memory.failures.append(obs.summary)
    elif tool.kind in ("read", "compute"):
        data = res.data
        n = len(data) if isinstance(data, list) else 1
        if pc.tool == "group_records":
            obs.summary = (f"{n} customer(s) meet the threshold (out of {res.metadata.get('groups_total', '?')} "
                           f"customers with matching records)")
        else:
            obs.summary = f"Found {n} {PLURAL.get(tool.entity, 'records')}"
            if "total_amount" in res.metadata and n:
                obs.summary += f" totalling ₹{res.metadata['total_amount']:,.0f}"
        if step.expect and step.expect.min_results is not None:
            obs.expected, obs.actual = f"≥ {step.expect.min_results} result(s)", str(n)
            obs.expectation_met = n >= step.expect.min_results
            if not obs.expectation_met:
                obs.notes.append("No records match these conditions. I will not broaden the filters on my own, "
                                 "since that would change what you asked for; dependent steps have nothing to act on.")
        obs.notes += _unique_discrepancies(s, step)
        requested = pc.args.get("ids") if pc.tool == "search_customers" else None
        if requested and isinstance(data, list) and len(data) < len(requested):
            missing = sorted(set(requested) - {r["id"] for r in data})
            obs.notes.append(f"Asked for {len(requested)} customers but the CRM returned {len(data)}; missing ids: {missing}")
        if tool.entity in ("invoice", "customer", "ticket") and isinstance(data, list):
            bucket = s.memory.records.setdefault(tool.entity, {})
            for rec in data:
                bucket[str(rec["id"])] = rec
    else:  # write
        data = res.data if isinstance(res.data, dict) else {}
        target = None
        try:
            target = tool.mutation_target(rt.registry.validate_args(pc.tool, pc.args))
        except Exception:  # noqa: BLE001 - already validated before execution
            pass
        if target is not None and data.get("after") != target.desired:
            obs.ok = False
            obs.summary = f"{pc.tool} reported success but returned {data.get('after')!r} instead of {target.desired!r}"
        elif "before" in data:
            label = data.get("label", "")
            obs.summary = (f"{label}: {data['field']} {data['before']} → {data['after']}" if data.get("changed")
                           else f"{label}: {data['field']} already {data['after']} (no change)")
            obs.expected, obs.actual = f"{data['field']} = {target.desired if target else data['after']}", str(data["after"])
        else:
            obs.summary = f"{pc.tool} succeeded" + (f": {data.get('label') or data.get('file')}" if data else "")
        s.memory.actions.append(obs.summary)

    s.observations.append(obs)
    rt.emit(s, "observation", node="observe_result", step_id=step.id, call_id=s.last_call_id, tool=pc.tool,
            status="success" if obs.ok and not obs.notes else ("warning" if obs.ok else "error"),
            title=obs.summary, notes=obs.notes, expected=obs.expected, actual=obs.actual)
    s.route = "evaluate"
    return updates(s)


def evaluate_result(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    pc, res, obs = s.pending_call, s.last_result, s.observations[-1]
    assert pc is not None and res is not None
    if res.success and not obs.ok:
        # The tool claimed success but its own output contradicts the request.
        s.last_result = res.model_copy(update={"success": False, "error": obs.summary,
                                               "error_code": ErrorCode.CONFLICT, "retryable": False})
        s.route = "recover"
        return updates(s)
    if not res.success:
        s.route = "recover"
        return updates(s)

    step = _step(s, pc.step_id)
    sr = s.step_runs[step.id]
    tool = rt.registry.get(pc.tool)
    if tool.kind == "write":
        s.evidence.append(_evidence(pc.tool, tool.entity, res.data, res.metadata, s.last_call_id, pc.attempt))
    if pc.attempt > 1 or pc.original_tool:
        how = f"after {pc.attempt - 1} retr{'y' if pc.attempt == 2 else 'ies'}" if pc.attempt > 1 else ""
        if pc.original_tool:
            how = f"using fallback tool {pc.tool} instead of {pc.original_tool}" + (f", {how}" if how else "")
        rt.emit(s, "recovery", node="evaluate_result", status="success", step_id=step.id, tool=pc.tool,
                title=f"Recovered: call succeeded {how}")
        s.memory.actions.append(f"Recovered {pc.tool} {how}")

    if pc.item_index is not None:
        sr.outputs.append(res.data)
        sr.item_status[pc.item_index] = "succeeded"
        sr.item_index = pc.item_index + 1
    else:
        sr.output = {"data": res.data, "metadata": res.metadata}
        finish_step(s, rt, step, sr)
    s.pending_call = None
    s.route = "next"
    return updates(s)


def _evidence(tool: str, entity: str | None, data: Any, metadata: dict[str, Any], call_id: str | None,
              attempts: int) -> EvidenceItem:
    data = data if isinstance(data, dict) else {}
    details = {"tool": tool, "attempts": attempts, **({"screenshot": metadata["screenshot"]} if "screenshot" in metadata else {})}
    if "before" in data:
        eid = data.get("customer_id") or data.get("ticket_id")
        return EvidenceItem(kind="change", entity=entity, entity_id=eid, label=data.get("label"), field=data.get("field"),
                            before=data.get("before"), after=data.get("after"), call_id=call_id,
                            details={**details, "changed": data.get("changed", True)})
    if tool == "export_report":
        return EvidenceItem(kind="artifact", entity="report", label=data.get("file"), call_id=call_id,
                            details={**details, **data})
    return EvidenceItem(kind="message" if tool == "send_customer_email" else "change", entity=entity,
                        entity_id=data.get("customer_id"), label=data.get("label") or data.get("to"),
                        call_id=call_id, details={**details, **data})
