"""End-to-end agent runs through the real LangGraph graph and the real (temp) database."""
import json
import os

from sqlalchemy import func, select

from app.agent.llm import LLMProvider
from app.agent.prompts import PLAN_SYSTEM
from app.agent.graph import make_checkpointer, make_serde
from app.database.models import Approval, AuditLog, Evidence, Run
from app.database.session import session_scope
from app.services.event_bus import history
from app.services.scenarios import DEMO_GOAL
from app.services.state_reader import StateReader
from app.services.task_service import RunManager
from app.tests.conftest import run_task
from app.tools.browser_tools import BROWSER_TOOLS
from app.tools.compute_tools import COMPUTE_TOOLS
from app.tools.crm_tools import CRM_TOOLS
from app.tools.file_tools import FILE_TOOLS
from app.tools.tool_registry import ToolRegistry

READER = StateReader()
TASK1_CUSTOMERS = [1, 3, 7, 11]
TIMEOUT_ONCE = [{"tool": "update_customer_status", "times": 1, "error": "Temporary database timeout"}]


def status_of(cid):
    return READER.read_field("customer", cid, "status")[1]


def event_types(run_id):
    return [e["type"] for e in history(run_id)]


def test_goal_plan_failure_recovery_approval_verification_end_to_end(manager, sleeps):
    """USER GOAL → PLAN → TOOL EXECUTION → FAILURE → RECOVERY → UPDATE → VERIFICATION → FINAL RESULT."""
    run_id, st = run_task(manager, DEMO_GOAL, faults=TIMEOUT_ONCE)

    # Paused for a human before any write.
    assert st.status == "awaiting_approval"
    assert [status_of(c) for c in TASK1_CUSTOMERS] == ["Active"] * 4
    assert st.approvals[-1].message.startswith("I found 4 customers")

    manager.decide(run_id, approved=True, by="tester", background=False)
    st = manager.state(run_id)

    assert st.status == "completed"
    assert [status_of(c) for c in TASK1_CUSTOMERS] == ["High Priority"] * 4
    assert st.retry_count == 1 and sleeps == [0.5]  # one transient failure, exponential backoff base
    failed = [c for c in st.tool_calls if not c.result.success]
    assert len(failed) == 1 and failed[0].injected_fault and failed[0].result.retryable
    assert st.verification_results[-1].passed
    fr = st.final_result
    assert fr.metrics["records_changed"] == 4 and fr.metrics["recovered_failures"] == 1
    assert {e.entity_id for e in fr.changes} == set(TASK1_CUSTOMERS) and all(e.verified for e in fr.changes)

    types = event_types(run_id)
    for t in ["goal", "plan", "tool_call", "observation", "retry", "approval_required", "approval_decision",
              "verification", "summary", "run_completed"]:
        assert t in types, t
    with session_scope() as db:
        assert db.get(Run, run_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.run_id == run_id)) >= 4
        tool_logs = db.scalars(select(AuditLog).where(AuditLog.run_id == run_id, AuditLog.tool.is_not(None))).all()
        assert len([a for a in tool_logs if a.agent_step == "execute_action"]) == len(st.tool_calls)
        assert db.scalar(select(Approval).where(Approval.run_id == run_id)).status == "approved"


def test_rejection_stops_safely_without_changes(manager):
    run_id, st = run_task(manager, DEMO_GOAL)
    manager.decide(run_id, approved=False, by="tester", comment="not now", background=False)
    st = manager.state(run_id)
    assert st.status == "rejected"
    assert st.final_result.headline.startswith("Stopped safely")
    assert [status_of(c) for c in TASK1_CUSTOMERS] == ["Active"] * 4
    assert not any(c.tool == "update_customer_status" for c in st.tool_calls)


def test_lost_write_is_caught_by_independent_verification_and_remediated(manager):
    faults = [{"tool": "update_customer_status", "mode": "lost_write", "match": {"customer_id": 7}}]
    _, st = run_task(manager, DEMO_GOAL, faults=faults, auto_approve=True)
    assert [v.passed for v in st.verification_results] == [False, True]
    assert any(s.remediation_of == "s3" for s in st.plan.steps)
    assert status_of(7) == "High Priority"
    lost = [e for e in st.evidence if e.entity_id == 7]
    assert [e.verified for e in lost] == [False, True]
    assert st.status == "completed"


def test_retries_are_bounded_and_failure_is_reported(manager, sleeps):
    faults = [{"tool": "update_customer_status", "times": 50, "match": {"customer_id": 3}}]
    _, st = run_task(manager, DEMO_GOAL, faults=faults, auto_approve=True)
    attempts_on_3 = [c for c in st.tool_calls if c.args.get("customer_id") == 3]
    # 1 + 3 retries, then one verification-driven remediation attempt (1 + 3 retries) — never unbounded.
    assert len(attempts_on_3) == 8
    assert sleeps[:3] == [0.5, 1.0, 2.0]
    assert status_of(3) == "Active" and [status_of(c) for c in (1, 7, 11)] == ["High Priority"] * 3
    assert st.status == "needs_attention" and not st.verification_results[-1].passed
    assert "Human review needed" in st.final_result.headline


def test_non_retryable_error_stops_branch_and_continues(manager, sleeps):
    faults = [{"tool": "update_customer_status", "match": {"customer_id": 7}, "error_code": "NOT_FOUND",
               "error": "Customer record locked by legal hold"}]
    _, st = run_task(manager, DEMO_GOAL, faults=faults, auto_approve=True)
    assert sleeps == []  # no retry for non-retryable errors
    assert st.step_runs["s3"].item_status == ["succeeded", "succeeded", "failed", "succeeded"]
    assert not any(s.remediation_of for s in st.plan.steps)  # not remediable
    assert st.status == "needs_attention"


def test_task4_skips_already_compliant_records(manager):
    run_id, st = run_task(manager, "Find customers with open high-priority support tickets and update their status to At Risk.")
    assert "3 CRM record(s)" in st.approvals[-1].message and "1 already in the desired state" in st.approvals[-1].message
    manager.decide(run_id, True, background=False)
    st = manager.state(run_id)
    assert st.step_runs["s3"].item_status.count("compliant") == 1
    assert len([c for c in st.tool_calls if c.tool == "update_customer_status"]) == 3
    assert [status_of(c) for c in (2, 9, 10, 15)] == ["At Risk"] * 4
    assert st.status == "completed"


def test_task2_read_only_with_discrepancy_reasoning(manager):
    _, st = run_task(manager, "Find all open support tickets with high priority and show me the affected customers.")
    assert st.status == "completed" and st.approvals == []
    assert sorted(c["id"] for c in st.step_runs["s2"].output["data"]) == [2, 9, 10, 15]
    assert any("map to 4 distinct customers" in n for o in st.observations for n in o.notes)


def test_task3_customers_with_multiple_overdue_invoices(manager):
    _, st = run_task(manager, "Find overdue invoices and identify customers who have more than one overdue invoice.")
    assert st.status == "completed"
    assert sorted(c["company"] for c in st.step_runs["s3"].output["data"]) == ["Epsilon Pharma", "Iota Motors", "Theta Healthcare"]
    assert st.verification_results[-1].passed


def test_nothing_matched_is_not_reported_as_success(manager):
    _, st = run_task(manager, "Mark customer #999 as At Risk", auto_approve=True)
    assert st.status == "needs_attention" and "No records matched" in st.final_result.headline


def test_unsupported_request_asks_for_clarification(manager):
    _, st = run_task(manager, "Delete all paid invoices")
    assert st.status == "needs_clarification" and st.tool_calls == []


def test_browser_failure_falls_back_to_api_tool(sleeps):
    registry = ToolRegistry(CRM_TOOLS + COMPUTE_TOOLS + FILE_TOOLS + BROWSER_TOOLS)
    from langgraph.checkpoint.memory import InMemorySaver

    m = RunManager(registry=registry, checkpointer=InMemorySaver(serde=make_serde()), sleep=sleeps)
    _, st = run_task(m, "Using the browser, mark customer #2 as At Risk", auto_approve=True)
    assert st.plan.steps[-1].tool == "browser_update_customer_status"
    assert any(e.resolution and "fallback" in e.resolution for e in st.errors)
    assert st.evidence[-1].details["tool"] == "update_customer_status"
    assert status_of(2) == "At Risk" and st.status == "completed"


def test_approval_survives_manager_restart(tmp_dir, sleeps):
    path = os.path.join(tmp_dir, "durable-checkpoints.db")
    first = RunManager(checkpointer=make_checkpointer(path), sleep=sleeps)
    run_id, st = run_task(first, DEMO_GOAL)
    assert st.status == "awaiting_approval"
    second = RunManager(checkpointer=make_checkpointer(path), sleep=sleeps)  # e.g. after a server restart
    second.decide(run_id, True, background=False)
    assert second.state(run_id).status == "completed"
    assert status_of(11) == "High Priority"


class ScriptedLLM(LLMProvider):
    """Fake LLM: returns canned JSON, including one invalid plan to exercise the validator."""

    name, model = "fake", "scripted"

    def __init__(self, plans):
        self.plans = list(plans)
        self.plan_prompts: list[str] = []

    def complete_json(self, system, user):
        if system == PLAN_SYSTEM:
            self.plan_prompts.append(user)
            return json.dumps(self.plans.pop(0))
        return json.dumps({
            "objective": "Prioritise customers with big unpaid invoices", "primary_entity": "invoice",
            "entities": ["invoice", "customer"],
            "conditions": [{"entity": "invoice", "field": "status", "operator": "equals", "value": "unpaid"},
                           {"entity": "invoice", "field": "amount", "operator": "greater_than", "value": 50000}],
            "actions": [{"type": "update_customer_status", "value": "High Priority"}],
        })


def test_llm_mode_invalid_plan_is_rejected_then_replanned(sleeps):
    bad = {"rationale": "x", "steps": [{"id": "s1", "description": "run sql", "tool": "execute_sql", "args": {"q": "UPDATE"}}]}
    good = {"rationale": "ok", "steps": [
        {"id": "s1", "description": "find", "tool": "search_invoices", "args": {"status": "unpaid", "amount_gt": 50000}},
        {"id": "s2", "description": "customers", "tool": "search_customers", "args": {"ids": "$s1.data[*].customer_id|unique"}},
        {"id": "s3", "description": "update", "tool": "update_customer_status", "for_each": "$s2.data",
         "args": {"customer_id": "$item.id", "status": "High Priority"}},
    ]}
    llm = ScriptedLLM([bad, good])
    from langgraph.checkpoint.memory import InMemorySaver

    m = RunManager(llm=llm, checkpointer=InMemorySaver(serde=make_serde()), sleep=sleeps)
    run_id, st = run_task(m, "prioritise customers with unpaid invoices over 50k", auto_approve=True)
    assert "execute_sql" in llm.plan_prompts[1] and "not in the allowlist" in llm.plan_prompts[1]
    assert st.plan.source == "llm" and st.status == "completed"
    assert [status_of(c) for c in TASK1_CUSTOMERS] == ["High Priority"] * 4
    assert st.mode == "llm"
