"""Prompts for LLM mode. Outputs are always validated before use."""
from __future__ import annotations

import json
from typing import Any

UNDERSTAND_SYSTEM = """You convert a business request about a CRM into a structured goal.
The CRM has: invoices (id, status: paid|unpaid|overdue, amount in INR, due_date, customer_id),
customers (id, status: Active|High Priority|At Risk|Inactive, risk_level: low|medium|high, name, company, email),
support tickets (id, status: open|in_progress|resolved|closed, priority: low|medium|high, customer_id).
'unpaid' means not yet due; 'overdue' means unpaid and past due.

Return ONLY JSON with this shape:
{
  "objective": str,
  "primary_entity": "invoice"|"customer"|"ticket",
  "entities": [..],
  "conditions": [{"entity": .., "field": .., "operator": "equals|not_equals|greater_than|greater_or_equal|less_than|less_or_equal|in", "value": ..}],
  "group_condition": null | {"entity": "invoice"|"ticket", "by": "customer_id", "min_count": int},
  "actions": [{"type": "update_customer_status|update_ticket_priority|send_customer_email|export_report|record_activity", "value": str|null, "channel": "api"|"browser"}],
  "required_actions": [short snake_case verbs],
  "ambiguities": [str],
  "clarification_needed": null | str
}
Rules: amounts are plain numbers (₹50,000 -> 50000). Only use the fields listed above.
"more than one X" -> group_condition min_count 2. Only include actions the user explicitly asked for.
If the request needs something the CRM cannot do (e.g. deleting records, payments), set clarification_needed."""


PLAN_SYSTEM = """You are the planner of an autonomous CRM worker. Produce an executable plan using ONLY the tools listed.
Return ONLY JSON: {"rationale": str, "steps": [{"id": "s1", "description": str, "tool": str, "args": {..},
"for_each": null | "$sN.data", "expect": null | {"min_results": int}}]}

Data flow between steps uses references (strings starting with $):
  "$s1.data"                         -> the records returned by step s1
  "$s1.data[*].customer_id|unique"   -> distinct customer ids from s1's records
  "$item.id"                         -> inside a for_each step, the current item's field
A step with "for_each" runs its tool once per item of the referenced list (use this for record updates).
Rules:
- Never invent tools or arguments. Use only argument names from each tool's input_schema.
- Read before you write. Resolve customers with search_customers(ids=...) when the goal concerns customers.
- One update call per record via for_each. Do not add a verification step; verification is done independently.
- Keep plans short (<= 8 steps)."""


def plan_user_prompt(goal: dict[str, Any], tools: list[dict[str, Any]], errors: list[str],
                     replan_reason: str | None) -> str:
    compact = [{k: t[k] for k in ("name", "description", "input_schema", "risk_level", "kind")} for t in tools]
    parts = [f"GOAL:\n{json.dumps(goal, indent=1)}", f"TOOLS:\n{json.dumps(compact)}"]
    if errors:
        parts.append("Your previous plan was rejected by the validator:\n- " + "\n- ".join(errors))
    if replan_reason:
        parts.append(f"Re-plan because execution failed: {replan_reason}")
    return "\n\n".join(parts)
