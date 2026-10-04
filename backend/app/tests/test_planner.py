"""Planner compilation, plan validation and the safe reference resolver."""
import pytest

from app.agent.planner import compile_plan, validate_plan
from app.agent.refs import RefError, resolve, resolve_ref
from app.agent.rule_parser import parse_goal
from app.agent.state import Plan, PlanStep
from app.tools.tool_registry import get_registry

REG = get_registry()


def plan_for(text):
    return compile_plan(parse_goal(text), REG)


def test_task1_plan_shape():
    plan = plan_for("Find unpaid invoices above ₹50,000 and mark their customers as High Priority.")
    assert [s.tool for s in plan.steps] == ["search_invoices", "search_customers", "update_customer_status"]
    assert plan.steps[0].args == {"status": "unpaid", "amount_gt": 50000.0}
    assert plan.steps[1].args["ids"] == "$s1.data[*].customer_id|unique"
    assert plan.steps[2].for_each == "$s2.data"
    assert validate_plan(plan, REG, 12) == []


def test_task3_plan_groups_before_resolving_customers():
    plan = plan_for("Find overdue invoices and identify customers who have more than one overdue invoice.")
    assert [s.tool for s in plan.steps] == ["search_invoices", "group_records", "search_customers"]
    assert plan.steps[2].args["ids"] == "$s2.data[*].key"


def test_all_example_plans_validate():
    for text in [
        "Find all open support tickets with high priority and show me the affected customers.",
        "Find customers with open high-priority support tickets and update their status to At Risk.",
        "overdue invoices under 20k from high risk customers, email them and export to csv",
    ]:
        assert validate_plan(plan_for(text), REG, 12) == [], text


def step(**kw):
    base = {"id": "s1", "description": "d", "tool": "search_invoices", "args": {}}
    return PlanStep(**{**base, **kw})


@pytest.mark.parametrize("steps,needle", [
    ([step(tool="delete_everything")], "not in the allowlist"),
    ([step(args={"sql": "DROP TABLE"})], "unknown argument"),
    ([step(tool="update_customer_status", args={"customer_id": 1})], "missing required"),
    ([step(args={"customer_ids": "$s9.data[*].id"})], "not an earlier step"),
    ([step(tool="get_customer", args={"customer_id": "$item.id"})], "has no for_each"),
    ([step(args={"status": "unpaid", "amount_gt": -5})], "greater than or equal"),
    ([step(args={"customer_ids": "$s1.data[*"})], "Malformed"),
    ([], "no steps"),
])
def test_validator_rejects_bad_plans(steps, needle):
    errors = validate_plan(Plan(steps=steps), REG, 12)
    assert any(needle.lower() in e.lower() for e in errors), errors


def test_validator_rejects_oversized_plans():
    plan = Plan(steps=[step(id=f"s{i}") for i in range(1, 15)])
    assert any("max" in e for e in validate_plan(plan, REG, 12))


def test_reference_resolver():
    scope = {"s1": {"data": [{"id": 1, "customer_id": 7}, {"id": 2, "customer_id": 7}, {"id": 3, "customer_id": 9}]},
             "item": {"id": 42}}
    assert resolve_ref("$s1.data[*].customer_id", scope) == [7, 7, 9]
    assert resolve_ref("$s1.data[*].customer_id|unique", scope) == [7, 9]
    assert resolve_ref("$s1.data[0].id", scope) == 1
    assert resolve({"ids": "$s1.data[*].id", "x": ["$item.id", 5]}, scope) == {"ids": [1, 2, 3], "x": [42, 5]}
    with pytest.raises(RefError):
        resolve_ref("$s1.data[*].nope", scope)
    with pytest.raises(RefError):
        resolve_ref("$s1.__class__", {"s1": object()})
