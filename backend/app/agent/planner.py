"""Goal understanding + planning + plan validation.

Both the LLM path and the DEMO rule path produce the same typed objects, and
both go through the same validator. Nothing the LLM writes is executed unless
it names an allowlisted tool with schema-valid arguments.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.agent import prompts
from app.agent.llm import LLMError, LLMProvider
from app.agent.refs import RefError, parse_ref, refs_in
from app.agent.rule_parser import describe_objective, parse_goal, required_actions
from app.agent.state import ENTITY_FIELDS, Condition, Plan, PlanStep, StepExpectation, StructuredGoal
from app.tools.base import ToolError
from app.tools.tool_registry import ToolRegistry

log = logging.getLogger(__name__)

ENUM_VALUES: dict[tuple[str, str], tuple[str, ...]] = {
    ("invoice", "status"): ("paid", "unpaid", "overdue"),
    ("customer", "status"): ("Active", "High Priority", "At Risk", "Inactive"),
    ("customer", "risk_level"): ("low", "medium", "high"),
    ("ticket", "status"): ("open", "in_progress", "resolved", "closed"),
    ("ticket", "priority"): ("low", "medium", "high"),
}


# ------------------------------------------------------------ understanding

def check_goal(goal: StructuredGoal) -> list[str]:
    """Semantic validation of a structured goal (field names and enum values)."""
    errors = []
    for c in goal.conditions:
        if c.field not in ENTITY_FIELDS[c.entity]:
            errors.append(f"Unknown field {c.entity}.{c.field}")
            continue
        allowed = ENUM_VALUES.get((c.entity, c.field))
        values = c.value if isinstance(c.value, list) else [c.value]
        if allowed:
            canon = {a.lower(): a for a in allowed}
            bad = [v for v in values if str(v).lower() not in canon]
            if bad:
                errors.append(f"Invalid value(s) {bad} for {c.entity}.{c.field}; allowed: {list(allowed)}")
            else:
                fixed = [canon[str(v).lower()] for v in values]
                c.value = fixed if isinstance(c.value, list) else fixed[0]
        if c.field == "amount" and not all(isinstance(v, (int, float)) for v in values):
            errors.append("Amount conditions must be numeric")
    for a in goal.actions:
        if a.type == "update_customer_status" and a.value not in ENUM_VALUES[("customer", "status")]:
            errors.append(f"Invalid customer status '{a.value}'")
        if a.type == "update_ticket_priority" and a.value not in ENUM_VALUES[("ticket", "priority")]:
            errors.append(f"Invalid ticket priority '{a.value}'")
    return errors


def interpret_goal(text: str, llm: LLMProvider) -> tuple[StructuredGoal, str, list[str]]:
    """Returns (goal, source, notes)."""
    if llm.is_demo:
        return parse_goal(text), "rules", []
    try:
        goal = llm.structured(prompts.UNDERSTAND_SYSTEM, text, StructuredGoal)
        errors = check_goal(goal)
        if not errors:
            goal.required_actions = goal.required_actions or required_actions(goal)
            return goal, "llm", []
        note = f"LLM goal rejected by validator ({'; '.join(errors)}); used rule-based parser instead"
    except LLMError as exc:
        note = f"LLM unavailable ({exc}); used rule-based parser instead"
    log.warning(note)
    return parse_goal(text), "rules", [note]


# ----------------------------------------------------------------- planning

class _Builder:
    def __init__(self) -> None:
        self.steps: list[PlanStep] = []

    def add(self, tool: str, description: str, args: dict[str, Any], *, for_each: str | None = None,
            expect: StepExpectation | None = None) -> str:
        sid = f"s{len(self.steps) + 1}"
        self.steps.append(PlanStep(id=sid, description=description, tool=tool, args=args, for_each=for_each,
                                   expect=expect))
        return sid


def _filter_args(entity: str, conditions: list[Condition]) -> dict[str, Any]:
    """Translate goal conditions into search-tool arguments for one entity."""
    args: dict[str, Any] = {}
    amount_ops = {"greater_than": "amount_gt", "greater_or_equal": "amount_gte",
                  "less_than": "amount_lt", "less_or_equal": "amount_lte"}
    for c in conditions:
        if c.entity != entity:
            continue
        values = c.value if isinstance(c.value, list) else [c.value]
        if c.field == "amount" and c.operator in amount_ops:
            args[amount_ops[c.operator]] = c.value
        elif c.field == "due_date" and c.operator in ("less_than", "greater_than"):
            args["due_before" if c.operator == "less_than" else "due_after"] = c.value
        elif c.field == "id":
            args["ids" if entity == "customer" else f"{entity}_ids"] = [int(v) for v in values]
        elif c.field == "customer_id":
            args["customer_ids"] = [int(v) for v in values]
        elif c.field in ("status", "priority", "risk_level") and c.operator in ("equals", "in"):
            args[c.field] = values[0] if len(values) == 1 else values
        elif c.field in ("name", "company", "email"):
            args["query"] = str(c.value)
    return args


SEARCH_TOOL = {"invoice": "search_invoices", "ticket": "search_tickets", "customer": "search_customers"}


def compile_plan(goal: StructuredGoal, registry: ToolRegistry) -> Plan:
    """Deterministic goal -> plan compiler (DEMO mode, and fallback for LLM mode)."""
    b = _Builder()
    primary = goal.primary_entity
    noun = {"invoice": "invoices", "ticket": "support tickets", "customer": "customers"}[primary]
    primary_id = b.add(SEARCH_TOOL[primary], f"Search {noun} matching the goal's conditions",
                       _filter_args(primary, goal.conditions), expect=StepExpectation(min_results=1))
    answer_step = primary_id
    customer_ref = f"${primary_id}.data[*].customer_id|unique"

    if goal.group_condition:
        g = goal.group_condition
        gid = b.add("group_records", f"Group {noun} by customer and keep customers with ≥{g.min_count}",
                    {"records": f"${primary_id}.data", "by": g.by, "min_count": g.min_count,
                     **({"sum_field": "amount"} if g.entity == "invoice" else {})})
        customer_ref, answer_step = f"${gid}.data[*].key", gid

    customers_step = primary_id if primary == "customer" else None
    if customers_step is None and "customer" in goal.entities:
        customers_step = b.add("search_customers", "Retrieve the customers linked to those records",
                               {"ids": customer_ref, **_filter_args("customer", goal.conditions)})
        answer_step = customers_step

    for action in goal.actions:
        if action.type == "update_customer_status" and customers_step:
            browser = action.channel == "browser" and registry.has("browser_update_customer_status")
            tool = "browser_update_customer_status" if browser else "update_customer_status"
            args: dict[str, Any] = {"customer_id": "$item.id", "status": action.value}
            if not browser:
                args["reason"] = goal.objective[:300]
            b.add(tool, f"Set each customer's status to {action.value}" + (" through the CRM web UI" if browser else ""),
                  args, for_each=f"${customers_step}.data")
        elif action.type == "update_ticket_priority" and primary == "ticket":
            b.add("update_ticket_priority", f"Set each ticket's priority to {action.value}",
                  {"ticket_id": "$item.id", "priority": action.value}, for_each=f"${primary_id}.data")
        elif action.type == "record_activity" and customers_step:
            b.add("record_activity", "Log an activity note on each customer",
                  {"customer_id": "$item.id", "note": action.value or "Reviewed by CentrAlign Worker"},
                  for_each=f"${customers_step}.data")
        elif action.type == "send_customer_email" and customers_step:
            subject = action.value or "A message from your account team"
            b.add("send_customer_email", f"Email each customer: '{subject}'",
                  {"customer_id": "$item.id", "subject": subject,
                   "body": f"Hello,\n\nThis is a note from your account team regarding: {subject.lower()}. "
                           "Please reply to this email if you have any questions.\n\nRegards,\nCentrAlign"},
                  for_each=f"${customers_step}.data")
        elif action.type == "export_report":
            slug = re.sub(r"[^a-z0-9]+", "-", noun.lower()).strip("-")[:40] or "report"
            b.add("export_report", "Export the results to a CSV report",
                  {"filename": f"{slug}-report", "rows": f"${answer_step}.data"})

    rationale = (f"Search {noun} with the requested filters"
                 + (", group by customer" if goal.group_condition else "")
                 + (", resolve customers" if customers_step and customers_step != primary_id else "")
                 + (", then " + ", ".join(a.type for a in goal.actions) if goal.actions else "")
                 + ". Verification runs independently afterwards.")
    return Plan(steps=b.steps, rationale=rationale, source="rules")


def llm_plan(goal: StructuredGoal, llm: LLMProvider, registry: ToolRegistry, errors: list[str],
             replan_reason: str | None) -> Plan:
    user = prompts.plan_user_prompt(goal.model_dump(), registry.catalog(), errors, replan_reason)
    plan = llm.structured(prompts.PLAN_SYSTEM, user, Plan)
    plan.source = "llm"
    return plan


def create_plan(goal: StructuredGoal, llm: LLMProvider, registry: ToolRegistry, *, errors: list[str],
                replan_reason: str | None, attempt: int) -> tuple[Plan, list[str]]:
    notes: list[str] = []
    if not llm.is_demo and attempt <= 2:
        try:
            return llm_plan(goal, llm, registry, errors, replan_reason), notes
        except LLMError as exc:
            notes.append(f"LLM planning failed ({exc}); using the rule-based planner")
    elif not llm.is_demo:
        notes.append("LLM plans kept failing validation; using the rule-based planner")
    return compile_plan(goal, registry), notes


# --------------------------------------------------------------- validation

def validate_plan(plan: Plan, registry: ToolRegistry, max_steps: int) -> list[str]:
    errors: list[str] = []
    if not plan.steps:
        return ["Plan has no steps"]
    if len(plan.steps) > max_steps:
        errors.append(f"Plan has {len(plan.steps)} steps (max {max_steps})")
    seen: set[str] = set()
    for step in plan.steps:
        where = f"step {step.id} ({step.tool})"
        if step.id in seen:
            errors.append(f"Duplicate step id {step.id}")
        if not registry.has(step.tool):
            errors.append(f"{where}: tool is not in the allowlist")
            seen.add(step.id)
            continue
        tool = registry.get(step.tool)
        fields = tool.input_model.model_fields
        unknown = set(step.args) - set(fields)
        if unknown:
            errors.append(f"{where}: unknown argument(s) {sorted(unknown)}")
        missing = [n for n, f in fields.items() if f.is_required() and n not in step.args]
        if missing:
            errors.append(f"{where}: missing required argument(s) {missing}")
        iterates = step.for_each is not None or step.items is not None
        refs = refs_in(step.args) + ([step.for_each] if step.for_each else [])
        for ref in refs:
            try:
                root, _, _ = parse_ref(ref)
            except RefError as exc:
                errors.append(f"{where}: {exc}")
                continue
            if root == "item":
                if not iterates:
                    errors.append(f"{where}: uses $item but has no for_each")
            elif root not in seen:
                errors.append(f"{where}: references '{root}' which is not an earlier step")
        if step.for_each is not None and not step.for_each.startswith("$"):
            errors.append(f"{where}: for_each must be a reference")
        if not refs:
            try:
                registry.validate_args(step.tool, step.args)
            except ToolError as exc:
                errors.append(f"{where}: {exc.message}")
        seen.add(step.id)
    return errors


def ensure_objective(goal: StructuredGoal) -> StructuredGoal:
    if not goal.objective:
        goal.objective = describe_objective(goal)
    return goal
