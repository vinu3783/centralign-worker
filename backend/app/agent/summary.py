"""generate_summary and complete nodes.

The final report is assembled from recorded facts (tool results, evidence,
verification) — never from free-form LLM text — so it cannot claim work that
did not happen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agent.runtime import PLURAL, AgentRuntime, updates
from app.agent.state import AgentState, EvidenceItem, FinalResult, ResultTable
from app.services import memory_service, run_store

COLUMNS = {
    "invoice": ["invoice_number", "customer_name", "amount", "due_date", "status"],
    "customer": ["id", "company", "name", "status", "risk_level"],
    "ticket": ["id", "subject", "customer_name", "priority", "status"],
    "group": ["key", "label", "count", "total"],
}


def compute_metrics(s: AgentState) -> dict[str, Any]:
    start = datetime.fromisoformat(s.started_at)
    wait_ms = 0.0
    for a in s.approvals:
        if a.decided_at and a.status in ("approved", "rejected"):
            wait_ms += (datetime.fromisoformat(a.decided_at) - datetime.fromisoformat(a.requested_at)).total_seconds() * 1000
    ok = [c for c in s.tool_calls if c.result.success]
    recovered = (sum(1 for c in ok if c.attempt > 1) + sum(1 for e in s.errors if "fallback" in (e.resolution or ""))
                 + sum(1 for e in s.evidence if e.verified is False and any(
                     x is not e and x.verified and (x.entity, x.entity_id, x.field) == (e.entity, e.entity_id, e.field)
                     for x in s.evidence)))
    ver = s.verification_results[-1] if s.verification_results else None
    return {
        "duration_ms": round((datetime.now(timezone.utc) - start).total_seconds() * 1000),
        "approval_wait_ms": round(wait_ms),
        "tool_calls": len(s.tool_calls),
        "successful_calls": len(ok),
        "failed_calls": len(s.tool_calls) - len(ok),
        "retries": s.retry_count,
        "recovered_failures": recovered,
        "approvals_requested": sum(1 for a in s.approvals if a.status != "auto_approved"),
        "records_changed": len({(e.entity, e.entity_id, e.field) for e in s.evidence if e.kind == "change"
                                and e.details.get("changed", True) and e.verified is not False}),
        "tools_used": sorted({c.tool for c in s.tool_calls}),
        "verification": None if ver is None else ("pass" if ver.passed else "fail"),
        "plan_source": s.plan.source if s.plan else None,
    }


def _result_tables(s: AgentState, rt: AgentRuntime) -> list[ResultTable]:
    tables = []
    mutated_customers = {e.entity_id for e in s.evidence if e.entity == "customer" and e.field == "status"}
    for step in (s.plan.steps if s.plan else []):
        sr = s.step_runs.get(step.id)
        tool = rt.registry.get(step.tool)
        if not sr or not sr.output or tool.kind not in ("read", "compute") or not isinstance(sr.output["data"], list):
            continue
        entity = "group" if step.tool == "group_records" else tool.entity
        rows = [dict(r) for r in sr.output["data"]][:100]
        cols = list(COLUMNS.get(entity or "", rows[0].keys() if rows else []))
        if entity == "customer" and mutated_customers:
            for r in rows:  # show the state now, next to what we saw when we started
                r["status_before"] = r["status"]
                r["status"] = rt.reader.read_field("customer", r["id"], "status")[1]
            cols.insert(cols.index("status"), "status_before")
        tables.append(ResultTable(title=step.description, entity=entity, columns=cols, rows=rows))
    return tables


def _lines(s: AgentState, rt: AgentRuntime) -> list[str]:
    lines = []
    for step in (s.plan.steps if s.plan else []):
        sr = s.step_runs.get(step.id)
        if sr is None:
            lines.append(f"Not reached: {step.description}")
            continue
        tool = rt.registry.get(step.tool)
        if tool.kind in ("read", "compute"):
            n = len(sr.output["data"]) if sr.output and isinstance(sr.output["data"], list) else 0
            noun = "customers meet the grouping threshold" if step.tool == "group_records" else \
                f"{PLURAL.get(tool.entity, 'records')} {'identified' if tool.entity == 'customer' else 'found'}"
            lines.append(f"{n} {noun}")
        elif sr.status == "rejected":
            lines.append(f"{step.tool}: rejected by a human — no changes made")
        elif sr.status == "skipped":
            lines.append(f"Skipped '{step.description}': {sr.notes[0] if sr.notes else 'nothing to do'}")
        else:
            st = sr.item_status or []
            done = [e for e in s.evidence if e.call_id and any(c.id == e.call_id and c.step_id == step.id for c in s.tool_calls)]
            changed = sum(1 for e in done if e.details.get("changed", True) and e.verified is not False)
            lost = sum(1 for e in done if e.verified is False)
            if changed or not st:
                verb = {"export_report": "report(s) exported", "send_customer_email": "email(s) queued in the outbox",
                        "record_activity": "activity note(s) logged"}.get(step.tool, f"{PLURAL.get(tool.entity, 'records')[:-1]} record(s) updated")
                lines.append(f"{changed} {verb}" + (f" ({step.description.lower()})" if tool.entity in ("customer", "ticket") else ""))
            if lost:
                lines.append(f"{lost} write(s) reported success but were NOT persisted — caught by independent verification")
            if st.count("compliant"):
                lines.append(f"{st.count('compliant')} already in the desired state (left unchanged)")
            if st.count("failed"):
                lines.append(f"{st.count('failed')} failed: " + "; ".join(sr.notes[-st.count('failed'):]))
    m = compute_metrics(s)
    if m["recovered_failures"]:
        lines.append(f"{m['recovered_failures']} failure(s) detected and recovered")
    if s.verification_results:
        v = s.verification_results[-1]
        lines.append(f"Verification {'passed' if v.passed else 'FAILED'} ({v.summary.split(' — ')[1]})"
                     + (f" after {len(s.verification_results)} attempts" if len(s.verification_results) > 1 else ""))
    return lines


def _nothing_matched(s: AgentState) -> bool:
    return any(o.expectation_met is False for o in s.observations)


def generate_summary(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    goal = s.normalized_goal
    if s.status == "needs_clarification":
        status, headline = "needs_clarification", f"I need clarification: {goal.clarification_needed if goal else ''}"
    elif s.status == "rejected":
        status = "rejected"
        prior = sum(1 for e in s.evidence if e.kind == "change" and e.details.get("changed", True))
        headline = ("Stopped safely: the change was rejected. No records were modified." if not prior else
                    f"Stopped safely after rejection. {prior} change(s) made before the rejected step remain.")
    elif s.status == "failed":
        status = "failed"
        last = s.errors[-1].error if s.errors else (s.plan_errors[-1] if s.plan_errors else "unknown error")
        headline = f"Task failed and was stopped safely: {last}"
    elif s.verification_results and s.verification_results[-1].passed and _nothing_matched(s) and goal and goal.actions:
        # Verification can't fail on zero targets, but the requested change did not happen.
        status = "needs_attention"
        headline = ("No records matched the conditions, so no changes were made. "
                    "Please check the request (ids, filters) — I did not broaden it on my own.")
    elif s.verification_results and s.verification_results[-1].passed:
        status = "completed"
        headline = ("Task completed — no records matched the conditions." if _nothing_matched(s)
                    else "Task completed successfully.")
    else:
        status = "needs_attention"
        headline = "Task incomplete — verification found records that are not in the requested state. Human review needed."

    changes = [e for e in s.evidence if e.kind in ("change", "message", "artifact")]
    s.final_result = FinalResult(status=status, headline=headline, summary_lines=_lines(s, rt), changes=changes,
                                 results=_result_tables(s, rt), metrics=compute_metrics(s),
                                 verification=s.verification_results[-1] if s.verification_results else None)
    s.status = status
    rt.emit(s, "summary", node="generate_summary", status="success" if status == "completed" else
            ("error" if status in ("failed", "needs_attention") else "warning"),
            title=headline, lines=s.final_result.summary_lines)
    return updates(s)


def complete(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    fr = s.final_result
    assert fr is not None
    sources = []
    for entity, recs in s.memory.records.items():
        for rid, rec in list(recs.items())[:50]:
            sources.append(EvidenceItem(kind="source_record", entity=entity, entity_id=int(rid),
                                        label=rec.get("invoice_number") or rec.get("company") or rec.get("subject"),
                                        details=rec))
    run_store.save_evidence(s.run_id, s.evidence + sources)
    run_store.update_run(s.run_id, status=fr.status, final_result=fr, metrics=fr.metrics,
                         verification_passed=fr.verification.passed if fr.verification else None,
                         finished_at=datetime.now(timezone.utc), plan=s.plan,
                         error=fr.headline if fr.status == "failed" else None)
    if s.normalized_goal and fr.status != "needs_clarification":
        transient: dict[str, int] = {}
        for e in s.errors:
            if e.retryable:
                transient[e.tool] = transient.get(e.tool, 0) + 1
        memory_service.remember_outcome(s.normalized_goal, s.run_id,
                                        {"status": fr.status, "records_changed": fr.metrics["records_changed"],
                                         "headline": fr.headline}, transient)
    rt.audit(s, "complete", output={"status": fr.status, "metrics": fr.metrics}, status=fr.status)
    rt.emit(s, "run_completed", node="complete", status="success" if fr.status == "completed" else "warning",
            title=f"Run finished: {fr.status}", final_status=fr.status, metrics=fr.metrics)
    return updates(s)
