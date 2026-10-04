"""verify_outcome node: independently check that the requested outcome holds.

Tool results are never trusted as proof. The verifier:
1. re-reads every targeted record from ground truth (fresh DB session via
   StateReader, not the tool that wrote it) and compares with the desired value;
2. checks every returned record actually satisfies the filters that produced it;
3. re-runs read queries whose filters were not affected by the run's writes and
   compares the result sets;
4. checks side-effect artifacts (outbox messages, CSV files) exist.

On failure it can append a bounded remediation step (once) for mismatches that
were caused by transient errors or silently lost writes.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.agent.refs import RefError, resolve
from app.agent.runtime import AgentRuntime, item_args, ref_scope, updates
from app.agent.state import AgentState, PlanStep, StepRun, VerificationCheck, VerificationResult
from app.tools.base import ToolContext

MAX_VERIFY_ATTEMPTS = 2


def _matches(actual: Any, op: str, expected: Any) -> bool:
    if op == "in":
        return actual in (expected if isinstance(expected, list) else [expected])
    if actual is None:
        return False
    expected = expected.isoformat() if hasattr(expected, "isoformat") else expected
    return {"greater_than": actual > expected, "greater_or_equal": actual >= expected,
            "less_than": actual < expected, "less_or_equal": actual <= expected,
            "equals": actual == expected}[op]


def _write_targets(s: AgentState, rt: AgentRuntime) -> dict[tuple[str, int, str], dict[str, Any]]:
    """Every (entity, id, field) the run intended to change -> desired value + provenance."""
    targets: dict[tuple[str, int, str], dict[str, Any]] = {}
    assert s.plan is not None
    for step in s.plan.steps:
        sr = s.step_runs.get(step.id)
        tool = rt.registry.get(step.tool)
        if sr is None or tool.kind != "write" or sr.approved is False or sr.status == "pending":
            continue
        for j, args in item_args(s, step, sr):
            try:
                target = tool.mutation_target(rt.registry.validate_args(step.tool, args))
            except Exception:  # noqa: BLE001 - invalid args were already reported as errors
                continue
            if target is None:
                continue
            status = sr.item_status[j] if j is not None else ("succeeded" if sr.output else "failed")
            item = (sr.items or [None])[j] if j is not None else None
            targets[(target.entity, target.entity_id, target.field)] = {
                "desired": target.desired, "step_id": step.remediation_of or step.id, "item": item,
                "item_status": status, "tool": step.tool,
            }
    return targets


def _record_state_checks(s: AgentState, rt: AgentRuntime, targets: dict) -> list[VerificationCheck]:
    groups: dict[tuple[str, str, Any], list[dict[str, Any]]] = defaultdict(list)
    for (entity, eid, field), t in targets.items():
        exists, actual = rt.reader.read_field(entity, eid, field)
        groups[(entity, field, t["desired"])].append({
            "entity": entity, "entity_id": eid, "label": rt.reader.label(entity, eid) or f"{entity} {eid}",
            "field": field, "expected": t["desired"], "observed": actual if exists else "<record not found>",
            "passed": exists and actual == t["desired"]})
    checks = []
    for (entity, field, desired), rows in groups.items():
        ok = sum(r["passed"] for r in rows)
        checks.append(VerificationCheck(
            name=f"Re-read {len(rows)} {entity} record(s): {field} = {desired}", kind="record_state",
            expected=len(rows), observed=ok, passed=ok == len(rows), details=rows))
    return checks


def _read_step_checks(s: AgentState, rt: AgentRuntime, mutated: set[tuple[str, str]]) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    assert s.plan is not None
    for step in s.plan.steps:
        sr = s.step_runs.get(step.id)
        tool = rt.registry.get(step.tool)
        if sr is None or sr.output is None or tool.kind != "read" or not tool.filter_semantics:
            continue
        records = sr.output.get("data") or []
        if not isinstance(records, list):
            continue
        try:
            args = resolve(step.args, ref_scope(s))
        except RefError:
            continue
        filters = {a: tool.filter_semantics[a] for a, v in args.items() if v is not None and a in tool.filter_semantics}
        bad = []
        for rec in records:
            for arg, (field, op) in filters.items():
                if not _matches(rec.get(field), op, args[arg]):
                    bad.append({"record_id": rec.get("id"), "field": field, "value": rec.get(field),
                                "rule": f"{op} {args[arg]}", "passed": False})
        desc = ", ".join(f"{f} {op}" for f, op in filters.values()) or "no filters"
        checks.append(VerificationCheck(
            name=f"{step.id}: all {len(records)} returned {tool.entity} record(s) satisfy the filters ({desc})",
            kind="filter_conformance", expected=len(records), observed=len(records) - len({b['record_id'] for b in bad}),
            passed=not bad, details=bad[:20]))
        # Re-query only if this run did not modify a field the query filters on.
        if tool.channel == "api" and not any((tool.entity, f) in mutated for f, _ in filters.values()):
            ex = rt.registry.execute(step.tool, args, ToolContext(run_id=s.run_id))
            if ex.result.success:
                before = sorted(r["id"] for r in records)
                after = sorted(r["id"] for r in ex.result.data)
                checks.append(VerificationCheck(
                    name=f"{step.id}: re-running {step.tool} returns the same {len(after)} record(s)",
                    kind="requery_consistency", expected=before, observed=after, passed=before == after))
    return checks


def _artifact_checks(s: AgentState, rt: AgentRuntime) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    for ev in s.evidence:
        if ev.kind == "artifact" and ev.entity == "report":
            path = Path(rt.settings.reports_dir) / str(ev.details.get("file"))
            rows = sum(1 for _ in csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else None
            checks.append(VerificationCheck(name=f"Report file {path.name} exists with {ev.details.get('rows')} rows",
                                            kind="artifact", expected=ev.details.get("rows"), observed=rows,
                                            passed=rows == ev.details.get("rows")))
        if ev.kind == "message":
            mid = ev.details.get("message_id")
            found = isinstance(mid, int) and rt.reader.exists("outbox", mid)
            checks.append(VerificationCheck(name=f"Outbox message #{mid} to {ev.label} exists", kind="artifact",
                                            expected=True, observed=found, passed=found))
    return checks


def _remediation_step(s: AgentState, rt: AgentRuntime, failed: list[dict[str, Any]], attempt: int) -> PlanStep | None:
    """Re-apply changes that are missing because of transient failures or lost writes."""
    last_error = {(e.step_id, e.item_index): e for e in s.errors}
    by_step: dict[str, list[Any]] = defaultdict(list)
    assert s.plan is not None
    for t in failed:
        step = next(st for st in s.plan.steps if st.id == t["step_id"])
        sr = s.step_runs[step.id]
        idx = (sr.items or []).index(t["item"]) if t["item"] in (sr.items or []) else None
        err = last_error.get((step.id, idx))
        lost_write = t["item_status"] == "succeeded"
        if t["item"] is not None and (lost_write or (err is not None and err.retryable)):
            by_step[step.id].append(t["item"])
    if not by_step:
        return None
    sid, items = next(iter(by_step.items()))
    origin = next(st for st in s.plan.steps if st.id == sid)
    return PlanStep(id=f"{sid}_fix{attempt}", description=f"Re-apply {len(items)} change(s) that verification found missing",
                    tool=origin.tool, args=origin.args, items=items, remediation_of=sid)


def verify_outcome(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    attempt = len(s.verification_results) + 1
    s.status = "verifying"
    rt.emit(s, "node", node="verify_outcome", status="running",
            title=f"Verifying outcome independently (attempt {attempt})")

    targets = _write_targets(s, rt)
    mutated = {(e, f) for (e, _, f) in targets}
    checks = _record_state_checks(s, rt, targets) + _read_step_checks(s, rt, mutated) + _artifact_checks(s, rt)
    passed = all(c.passed for c in checks)
    n_ok = sum(c.passed for c in checks)
    summary = (f"PASS — {n_ok}/{len(checks)} checks passed" if passed
               else f"FAIL — {len(checks) - n_ok} of {len(checks)} checks failed")
    result = VerificationResult(attempt=attempt, passed=passed, checks=checks, summary=summary)
    s.verification_results.append(result)

    verified = {(r["entity"], r["entity_id"], r["field"]): r["passed"]
                for c in checks if c.kind == "record_state" for r in c.details}
    # Only the latest write to a record reflects its current state; an earlier write that
    # verification already flagged (e.g. a lost write) keeps its verified=False.
    latest = {(ev.entity, ev.entity_id, ev.field): ev for ev in s.evidence}
    for ev in s.evidence:
        key = (ev.entity, ev.entity_id, ev.field)
        if key in verified and (latest[key] is ev or ev.verified is None):
            ev.verified = verified[key]
    rt.emit(s, "verification", node="verify_outcome", status="success" if passed else "error", title=f"Verification {summary}",
            checks=[c.model_dump(mode="json") for c in checks], passed=passed, attempt=attempt)
    rt.audit(s, "verify_outcome", output=result.model_dump(mode="json"), status="success" if passed else "failed")

    if passed:
        s.route = "pass"
        return updates(s)
    failed_targets = [{**t, "key": k} for k, t in targets.items() if not verified.get(k, True)]
    fix = _remediation_step(s, rt, failed_targets, attempt) if attempt < MAX_VERIFY_ATTEMPTS else None
    if fix is not None and s.plan is not None:
        parent = s.step_runs[fix.remediation_of or ""]
        s.plan.steps.append(fix)
        s.step_runs[fix.id] = StepRun(step_id=fix.id, approved=parent.approved)
        s.pending_steps.append(fix.id)
        s.current_step = len(s.plan.steps) - 1
        s.status = "running"
        rt.emit(s, "recovery", node="verify_outcome", status="warning", step_id=fix.id, tool=fix.tool,
                title=f"Verification found {len(fix.items or [])} record(s) not in the desired state — "
                      f"re-applying (covered by the earlier approval), then verifying again")
        s.route = "remediate"
    else:
        s.route = "fail"
    return updates(s)
