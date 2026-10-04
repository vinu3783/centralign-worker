"""Goal understanding (DEMO-mode rule parser) and semantic goal validation."""
import pytest

from app.agent.planner import check_goal
from app.agent.rule_parser import parse_goal
from app.agent.state import Condition, StructuredGoal


def conds(goal):
    return {(c.entity, c.field, c.operator, str(c.value)) for c in goal.conditions}


def test_task1_unpaid_invoices_high_priority():
    g = parse_goal("Find unpaid invoices above ₹50,000 and mark their customers as High Priority.")
    assert g.primary_entity == "invoice"
    assert g.entities == ["invoice", "customer"]
    assert conds(g) == {("invoice", "status", "equals", "unpaid"), ("invoice", "amount", "greater_than", "50000.0")}
    assert [(a.type, a.value) for a in g.actions] == [("update_customer_status", "High Priority")]
    assert g.required_actions[-1] == "verify_updates"


def test_task2_open_high_priority_tickets_read_only():
    g = parse_goal("Find all open support tickets with high priority and show me the affected customers.")
    assert g.primary_entity == "ticket"
    assert conds(g) == {("ticket", "status", "equals", "open"), ("ticket", "priority", "equals", "high")}
    assert g.actions == []
    assert "customer" in g.entities


def test_task3_group_condition():
    g = parse_goal("Find overdue invoices and identify customers who have more than one overdue invoice.")
    assert g.group_condition is not None and g.group_condition.min_count == 2
    assert conds(g) == {("invoice", "status", "equals", "overdue")}


def test_task4_status_action_does_not_leak_into_conditions():
    g = parse_goal("Find customers with open high-priority support tickets and update their status to At Risk.")
    assert g.primary_entity == "ticket"
    assert ("ticket", "priority", "equals", "high") in conds(g)
    assert not any(c.entity == "customer" for c in g.conditions)
    assert g.actions[0].value == "At Risk"


@pytest.mark.parametrize("text,value", [
    ("unpaid invoices over 50k", 50_000), ("unpaid invoices above 1.5 lakh", 150_000),
    ("unpaid invoices above Rs. 75,000", 75_000), ("unpaid invoices more than 2 crore", 20_000_000),
])
def test_amount_units(text, value):
    amount = [c for c in parse_goal(text).conditions if c.field == "amount"]
    assert amount and amount[0].value == value and amount[0].operator == "greater_than"


def test_between_and_less_than():
    g = parse_goal("paid invoices between 10k and 60k")
    assert ("invoice", "amount", "greater_or_equal", "10000.0") in conds(g)
    assert ("invoice", "amount", "less_or_equal", "60000.0") in conds(g)


def test_group_quantifier_does_not_become_amount():
    g = parse_goal("mark customers with more than 2 overdue invoices as At Risk")
    assert g.group_condition and g.group_condition.min_count == 3
    assert not any(c.field == "amount" for c in g.conditions)


def test_explicit_customer_id_and_browser_channel():
    g = parse_goal("Using the browser, mark customer #12 as Inactive")
    assert ("customer", "id", "in", "[12]") in conds(g)
    assert g.actions[0].channel == "browser"


@pytest.mark.parametrize("text", ["Delete all paid invoices", "Refund customer 3", "What's the weather today?"])
def test_unsupported_or_unrelated_requests_need_clarification(text):
    assert parse_goal(text).clarification_needed


def test_check_goal_rejects_unknown_fields_and_values():
    g = StructuredGoal(objective="x", primary_entity="invoice", entities=["invoice"], conditions=[
        Condition(entity="invoice", field="password", operator="equals", value="x"),
        Condition(entity="invoice", field="status", operator="equals", value="bogus"),
    ])
    errors = check_goal(g)
    assert any("Unknown field" in e for e in errors) and any("Invalid value" in e for e in errors)


def test_check_goal_canonicalizes_case():
    g = StructuredGoal(objective="x", primary_entity="customer", entities=["customer"],
                       conditions=[Condition(entity="customer", field="status", operator="equals", value="at risk")])
    assert check_goal(g) == [] and g.conditions[0].value == "At Risk"


def test_unparseable_long_request_asks_instead_of_guessing():
    g = parse_goal("Which clients owe us money that's already late? Bump the risky ones to At Risk.")
    assert g.clarification_needed
    assert parse_goal("show me all customers").clarification_needed is None


def test_llm_actions_must_be_grounded_in_the_request():
    from app.agent.planner import ground_actions
    from app.agent.state import GoalAction

    text = "Find unpaid invoices, update their status to High Priority, and verify that the updates were successful."
    g = StructuredGoal(objective="x", primary_entity="invoice", entities=["invoice", "customer"], actions=[
        GoalAction(type="update_customer_status", value="High Priority", evidence="update their status to High Priority"),
        GoalAction(type="record_activity", evidence="verify that the updates were successful"),  # real quote, wrong action
        GoalAction(type="export_report", evidence="export everything to csv"),  # not in the request
    ])
    notes = ground_actions(g, text)
    assert [a.type for a in g.actions] == ["update_customer_status"] and len(notes) == 2
