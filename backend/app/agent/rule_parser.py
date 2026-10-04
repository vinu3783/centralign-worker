"""DEMO-mode goal understanding: deterministic natural-language -> StructuredGoal.

This is a small compositional grammar (entities + conditions + actions), not a
lookup of known tasks: any combination of the supported phrases works, e.g.
"overdue invoices under 20k from high risk customers, export to csv".
"""
from __future__ import annotations

import re

from app.agent.state import Condition, GoalAction, GroupCondition, StructuredGoal

CUSTOMER_STATUS = {"high priority": "High Priority", "at risk": "At Risk", "active": "Active", "inactive": "Inactive"}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
               "cr": 1e7, "crore": 1e7, "crores": 1e7}
AMOUNT_OPS = {
    "above": "greater_than", "over": "greater_than", "greater than": "greater_than", "more than": "greater_than",
    "exceeding": "greater_than", "higher than": "greater_than", "at least": "greater_or_equal",
    "minimum of": "greater_or_equal", "below": "less_than", "under": "less_than", "less than": "less_than",
    "lower than": "less_than", "at most": "less_or_equal", "up to": "less_or_equal", "maximum of": "less_or_equal",
    ">": "greater_than", ">=": "greater_or_equal", "<": "less_than", "<=": "less_or_equal",
}

RE_INVOICE = re.compile(r"\b(invoices?|bills?|billing)\b")
RE_TICKET = re.compile(r"\b(tickets?|support (?:cases?|requests?|issues?))\b")
RE_CUSTOMER = re.compile(r"\b(customers?|clients?|accounts?)\b")
RE_UNSUPPORTED = re.compile(r"\b(delete|remove|erase|drop|refund|transfer|wire|write off|cancel|pay)\b")

RE_STATUS_ACTION = re.compile(
    r"\b(mark|set|update|change|flag|move|make|tag)\b(?P<obj>[^.;]*?)\b(?:as|to)\s+(?:an?\s+|the\s+)?"
    r"(?P<val>high priority|at risk|active|inactive)\b")
RE_PRIORITY_ACTION = re.compile(
    r"\b(set|update|change|raise|escalate|bump|lower|mark)\b(?P<obj>[^.;]*?)\b(?:to|as)\s+"
    r"(?P<val>low|medium|high)(?:\s+priority)?\b")
RE_EMAIL = re.compile(r"\b(email|e mail|notify|send (?:a |an )?(?:reminder|notice|message))\b")
RE_EXPORT = re.compile(r"\b(export|csv|spreadsheet|download|save (?:it |them |this |the results )?"
                       r"(?:as|to) (?:a )?(?:file|report)|write (?:a )?report)\b")
RE_NOTE = re.compile(r"\b(?:add|log|record) (?:a |an )?(?:note|activity)\b")
RE_BROWSER = re.compile(r"\b(browser|web ui|via the (?:crm )?ui|through the (?:crm )?ui|using the (?:crm )?ui|"
                        r"computer use|like a human)\b")

RE_GROUP = re.compile(r"\b(?P<op>more than|at least|over|multiple|several)\s*(?P<n>one|two|three|four|five|\d+)?\s+"
                      r"(?:\w+\s+){0,2}?(?P<ent>invoices?|tickets?)\b")
RE_AMOUNT = re.compile(
    r"(?P<op>above|over|greater than|more than|exceeding|higher than|at least|minimum of|below|under|"
    r"less than|lower than|at most|up to|maximum of|>=|<=|>|<)\s*(?:inr\s*)?(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<mult>k|thousand|lakhs?|lacs?|l|crores?|cr)?\b(?!\s*(?:invoices?|tickets?|days?|customers?))")
RE_BETWEEN = re.compile(r"\bbetween\s*(?:inr\s*)?(?P<a>\d+(?:\.\d+)?)\s*(?P<ma>k|lakhs?|l|cr)?\s*and\s*(?:inr\s*)?"
                        r"(?P<b>\d+(?:\.\d+)?)\s*(?P<mb>k|lakhs?|l|cr)?\b")
RE_TICKET_PRIORITY = re.compile(r"\b(high|medium|low)\s+priority\b|\bpriority\s+(?:is\s+)?(high|medium|low)\b|\burgent\b")
RE_RISK = re.compile(r"\b(high|medium|low)\s+risk\b|\brisk\s+(?:level\s+)?(?:is\s+|of\s+)?(high|medium|low)\b")
RE_CUSTOMER_STATUS = re.compile(
    r"\b(active|inactive|at risk|high priority)\s+(?:customers?|clients?|accounts?)\b|"
    r"\b(?:customers?|clients?|accounts?)\s+(?:who are|that are|with status|in status|marked)\s+"
    r"(active|inactive|at risk|high priority)\b")
RE_CUSTOMER_ID = re.compile(r"\b(?:customers?|clients?)\s*(?:#|id\s*|no\.?\s*|number\s*)?(\d+)\b|#(\d+)")


def normalize(text: str) -> str:
    t = text.lower().replace("₹", " inr ")
    t = re.sub(r"\brs\.?\s*(?=\d)", " inr ", t)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = t.replace("-", " ")
    return re.sub(r"\s+", " ", t).strip()


def _amount(num: str, mult: str | None) -> float:
    return float(num) * MULTIPLIERS.get(mult or "", 1)


def _blank(text: str, start: int, end: int) -> str:
    """Remove a consumed span so it isn't re-parsed as a condition."""
    return text[:start] + " | " + text[end:]


def _blank_action(text: str, m: re.Match[str]) -> str:
    """Blank the verb and the target value but keep the object phrase, which may hold
    conditions ("mark customers WITH MORE THAN 2 OVERDUE INVOICES as At Risk")."""
    return _blank(_blank(text, m.end("obj"), m.end()), m.start(), m.end(1))


def _inr(n: float) -> str:
    return f"₹{n:,.0f}"


def _cond_text(c: Condition) -> str:
    ops = {"equals": "=", "not_equals": "≠", "greater_than": ">", "greater_or_equal": "≥", "less_than": "<",
           "less_or_equal": "≤", "in": "in"}
    value = _inr(c.value) if c.field == "amount" else c.value
    return f"{c.field} {ops[c.operator]} {value}"


def parse_goal(text: str) -> StructuredGoal:
    t = normalize(text)
    positions = {name: (m.start() if (m := rx.search(t)) else None)
                 for name, rx in (("invoice", RE_INVOICE), ("ticket", RE_TICKET), ("customer", RE_CUSTOMER))}
    record_entities = [e for e in ("invoice", "ticket") if positions[e] is not None]
    primary = min(record_entities, key=lambda e: positions[e]) if record_entities else "customer"
    ambiguities: list[str] = []

    if m := RE_UNSUPPORTED.search(t):
        return _clarify(text, primary, f"'{m.group(1)}' is not an available capability. I can search records, "
                                       "update customer status or ticket priority, notify customers, and export reports.")
    if positions["customer"] is None and not record_entities:
        return _clarify(text, primary, "I couldn't relate this request to invoices, customers or support tickets.")

    # ---- actions (consumed spans are removed before parsing conditions)
    actions: list[GoalAction] = []
    channel = "browser" if RE_BROWSER.search(t) else "api"
    cond_text = t
    m = RE_PRIORITY_ACTION.search(cond_text)
    if m and primary == "ticket" and ("ticket" in m.group("obj") or "priority" in m.group(0)) \
            and not re.search(r"customer|status|account", m.group("obj")):
        actions.append(GoalAction(type="update_ticket_priority", value=m.group("val")))
        cond_text = _blank_action(cond_text, m)
    elif m := RE_STATUS_ACTION.search(cond_text):
        actions.append(GoalAction(type="update_customer_status", value=CUSTOMER_STATUS[m.group("val")], channel=channel))
        cond_text = _blank_action(cond_text, m)
    if RE_NOTE.search(t):
        actions.append(GoalAction(type="record_activity", value=f"Flagged by CentrAlign Worker: {text.strip()[:200]}"))
    if RE_EMAIL.search(t):
        subject = {"invoice": "Payment reminder", "ticket": "Update on your open support tickets"}.get(
            primary, "A message from your account team")
        actions.append(GoalAction(type="send_customer_email", value=subject))
    if RE_EXPORT.search(t):
        actions.append(GoalAction(type="export_report"))

    # ---- grouping ("customers with more than one overdue invoice")
    group: GroupCondition | None = None
    if (m := RE_GROUP.search(cond_text)) and positions["customer"] is not None:
        ent = "invoice" if m.group("ent").startswith("invoice") else "ticket"
        raw_n = m.group("n")
        n = NUMBER_WORDS.get(raw_n, int(raw_n) if raw_n and raw_n.isdigit() else 1)
        min_count = n + 1 if m.group("op") in ("more than", "over") else max(n, 2 if raw_n is None else n)
        group = GroupCondition(entity=ent, min_count=min_count)
        if ent != primary:
            primary = ent
        # Blank only the quantifier ("more than one") so adjectives like "overdue" still parse.
        cond_text = _blank(cond_text, m.start(), m.end("n") if raw_n else m.end("op"))

    conditions: list[Condition] = []
    if primary == "invoice" or positions["invoice"] is not None:
        conditions += _invoice_conditions(cond_text)
    if primary == "ticket" or positions["ticket"] is not None:
        conditions += _ticket_conditions(cond_text)
    conditions += _customer_conditions(cond_text, t)

    entities = [primary]
    involves_customer = positions["customer"] is not None or any(
        a.type in ("update_customer_status", "send_customer_email", "record_activity") for a in actions)
    if primary != "customer" and involves_customer:
        entities.append("customer")
    if any(a.type == "update_customer_status" for a in actions) and primary == "customer" and not conditions:
        ambiguities.append("No filter given: this would update every customer.")

    goal = StructuredGoal(
        objective="", primary_entity=primary, entities=entities, conditions=conditions,
        group_condition=group, actions=actions, ambiguities=ambiguities,
    )
    goal.objective = describe_objective(goal)
    goal.required_actions = required_actions(goal)
    return goal


def _invoice_conditions(t: str) -> list[Condition]:
    out: list[Condition] = []
    statuses: list[str] = []
    if re.search(r"\b(unpaid|not (?:yet )?paid)\b", t):
        statuses.append("unpaid")
    if re.search(r"\b(overdue|past due|late)\b", t):
        statuses.append("overdue")
    if re.search(r"\boutstanding\b", t):
        statuses += [s for s in ("unpaid", "overdue") if s not in statuses]
    if re.search(r"(?<!not )\bpaid\b", t) and not statuses:
        statuses.append("paid")
    if len(statuses) == 1:
        out.append(Condition(entity="invoice", field="status", operator="equals", value=statuses[0]))
    elif statuses:
        out.append(Condition(entity="invoice", field="status", operator="in", value=statuses))

    if m := RE_BETWEEN.search(t):
        out.append(Condition(entity="invoice", field="amount", operator="greater_or_equal",
                             value=_amount(m.group("a"), m.group("ma"))))
        out.append(Condition(entity="invoice", field="amount", operator="less_or_equal",
                             value=_amount(m.group("b"), m.group("mb"))))
    else:
        for m in RE_AMOUNT.finditer(t):
            out.append(Condition(entity="invoice", field="amount", operator=AMOUNT_OPS[m.group("op")],
                                 value=_amount(m.group("num"), m.group("mult"))))
    return out


def _ticket_conditions(t: str) -> list[Condition]:
    out: list[Condition] = []
    statuses: list[str] = []
    if re.search(r"\bunresolved\b", t):
        statuses += ["open", "in_progress"]
    else:
        if re.search(r"\bopen\b", t):
            statuses.append("open")
        if re.search(r"\bin progress\b", t):
            statuses.append("in_progress")
        if re.search(r"\bresolved\b", t):
            statuses.append("resolved")
        if re.search(r"\bclosed\b", t):
            statuses.append("closed")
    if len(statuses) == 1:
        out.append(Condition(entity="ticket", field="status", operator="equals", value=statuses[0]))
    elif statuses:
        out.append(Condition(entity="ticket", field="status", operator="in", value=statuses))
    if m := RE_TICKET_PRIORITY.search(t):
        out.append(Condition(entity="ticket", field="priority", operator="equals",
                             value=m.group(1) or m.group(2) or "high"))
    return out


def _customer_conditions(t: str, full_text: str) -> list[Condition]:
    out: list[Condition] = []
    if m := RE_RISK.search(t):
        out.append(Condition(entity="customer", field="risk_level", operator="equals", value=m.group(1) or m.group(2)))
    if m := RE_CUSTOMER_STATUS.search(t):
        out.append(Condition(entity="customer", field="status", operator="equals",
                             value=CUSTOMER_STATUS[m.group(1) or m.group(2)]))
    ids = [int(a or b) for a, b in RE_CUSTOMER_ID.findall(full_text)]
    if ids:
        out.append(Condition(entity="customer", field="id", operator="in", value=sorted(set(ids))))
    return out


def describe_objective(goal: StructuredGoal) -> str:
    plural = {"invoice": "invoices", "ticket": "support tickets", "customer": "customers"}
    parts = []
    primary_conds = [c for c in goal.conditions if c.entity == goal.primary_entity]
    desc = f"Find {plural[goal.primary_entity]}"
    if primary_conds:
        desc += " where " + " and ".join(_cond_text(c) for c in primary_conds)
    parts.append(desc)
    if goal.group_condition:
        parts.append(f"keep customers with ≥{goal.group_condition.min_count} such {plural[goal.group_condition.entity]}")
    if "customer" in goal.entities and goal.primary_entity != "customer":
        cust = [c for c in goal.conditions if c.entity == "customer"]
        parts.append("identify the customers" + (" where " + " and ".join(map(_cond_text, cust)) if cust else ""))
    for a in goal.actions:
        parts.append({
            "update_customer_status": f"set their status to {a.value}" + (" via the CRM UI" if a.channel == "browser" else ""),
            "update_ticket_priority": f"set ticket priority to {a.value}",
            "send_customer_email": f"email them ({a.value})",
            "export_report": "export the results to CSV",
            "record_activity": "log an activity note",
        }[a.type])
    return ", ".join(parts)


def required_actions(goal: StructuredGoal) -> list[str]:
    acts = [f"find_matching_{goal.primary_entity}s"]
    if goal.group_condition:
        acts.append("group_by_customer")
    if "customer" in goal.entities and goal.primary_entity != "customer":
        acts.append("identify_customers")
    acts += [a.type for a in goal.actions]
    writes = any(a.type != "export_report" for a in goal.actions)
    acts.append("verify_updates" if writes else "verify_results")
    return acts


def _clarify(text: str, primary: str, reason: str) -> StructuredGoal:
    return StructuredGoal(objective=text.strip(), primary_entity=primary, entities=[primary],
                          clarification_needed=reason)
