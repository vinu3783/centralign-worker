"""Typed agent state. Everything the agent knows lives here (no globals)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.tools.base import ToolResult
from app.tools.tool_registry import FaultSpec

Entity = Literal["invoice", "customer", "ticket"]
Operator = Literal["equals", "not_equals", "greater_than", "greater_or_equal", "less_than", "less_or_equal", "in"]

# Fields the goal may filter on, per entity. Anything else is rejected.
ENTITY_FIELDS: dict[str, set[str]] = {
    "invoice": {"id", "status", "amount", "due_date", "customer_id", "invoice_number"},
    "customer": {"id", "status", "risk_level", "name", "company", "email"},
    "ticket": {"id", "status", "priority", "customer_id"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------ goal & plan

class Condition(BaseModel):
    entity: Entity
    field: str
    operator: Operator
    value: Any


class GroupCondition(BaseModel):
    """e.g. 'customers with more than one overdue invoice' -> invoice by customer_id, min_count 2."""

    entity: Literal["invoice", "ticket"]
    by: Literal["customer_id"] = "customer_id"
    min_count: int = Field(ge=1)


ActionType = Literal["update_customer_status", "update_ticket_priority", "send_customer_email",
                     "export_report", "record_activity"]


class GoalAction(BaseModel):
    type: ActionType
    value: str | None = None  # new status / priority / email subject / note
    channel: Literal["api", "browser"] = "api"


class StructuredGoal(BaseModel):
    objective: str
    primary_entity: Entity
    entities: list[Entity]
    conditions: list[Condition] = []
    group_condition: GroupCondition | None = None
    actions: list[GoalAction] = []
    required_actions: list[str] = []
    ambiguities: list[str] = []
    clarification_needed: str | None = None


class StepExpectation(BaseModel):
    min_results: int | None = None
    max_results: int | None = None


class PlanStep(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    description: str
    tool: str
    args: dict[str, Any] = {}
    for_each: str | None = None  # reference to a list, e.g. "$s2.data"
    items: list[Any] | None = None  # literal item list (used for remediation steps)
    expect: StepExpectation | None = None
    remediation_of: str | None = None


class Plan(BaseModel):
    steps: list[PlanStep]
    rationale: str = ""
    source: Literal["llm", "rules"] = "rules"


# ------------------------------------------------------------- execution

ItemStatus = Literal["pending", "succeeded", "failed", "compliant"]


class StepRun(BaseModel):
    step_id: str
    status: Literal["pending", "running", "completed", "partial", "failed", "skipped", "rejected"] = "pending"
    items: list[Any] | None = None
    item_status: list[ItemStatus] = []
    item_index: int = 0
    outputs: list[Any] = []  # per-item data for for_each steps
    output: dict[str, Any] | None = None  # {"data":..., "metadata":...} for single-call steps
    approved: bool | None = None
    preview: list[dict[str, Any]] = []
    notes: list[str] = []


class PendingCall(BaseModel):
    step_id: str
    item_index: int | None = None
    tool: str
    args: dict[str, Any]
    attempt: int = 1
    original_tool: str | None = None  # set when we switched to a fallback tool


class ToolCallRecord(BaseModel):
    id: str
    step_id: str
    item_index: int | None
    tool: str
    args: dict[str, Any]
    attempt: int
    result: ToolResult
    duration_ms: float
    injected_fault: str | None = None
    timestamp: str = Field(default_factory=now_iso)


class Observation(BaseModel):
    step_id: str
    call_id: str | None
    summary: str
    expected: str | None = None
    actual: str | None = None
    ok: bool = True
    expectation_met: bool | None = None
    notes: list[str] = []


class ErrorRecord(BaseModel):
    step_id: str
    item_index: int | None
    tool: str
    error: str
    error_code: str | None
    retryable: bool
    attempt: int
    resolution: str | None = None
    timestamp: str = Field(default_factory=now_iso)


class ApprovalInfo(BaseModel):
    approval_id: int | None = None
    step_id: str
    tool: str
    risk_level: str
    message: str
    preview: list[dict[str, Any]] = []
    status: Literal["pending", "approved", "rejected", "auto_approved"] = "pending"
    decided_by: str | None = None
    comment: str | None = None
    requested_at: str = Field(default_factory=now_iso)
    decided_at: str | None = None


class VerificationCheck(BaseModel):
    name: str
    kind: Literal["record_state", "filter_conformance", "requery_consistency", "artifact"]
    expected: Any
    observed: Any
    passed: bool
    details: list[dict[str, Any]] = []


class VerificationResult(BaseModel):
    attempt: int
    passed: bool
    checks: list[VerificationCheck]
    summary: str
    timestamp: str = Field(default_factory=now_iso)


class EvidenceItem(BaseModel):
    kind: Literal["change", "source_record", "artifact", "message"]
    entity: str | None = None
    entity_id: int | None = None
    label: str | None = None
    field: str | None = None
    before: Any = None
    after: Any = None
    verified: bool | None = None
    call_id: str | None = None
    details: dict[str, Any] = {}
    timestamp: str = Field(default_factory=now_iso)


class WorkingMemory(BaseModel):
    """Structured within-run memory: what the agent has discovered and done."""

    records: dict[str, dict[str, dict[str, Any]]] = {}  # entity -> id -> latest record seen
    actions: list[str] = []
    failures: list[str] = []
    approvals: list[str] = []
    recalled: list[dict[str, Any]] = []  # cross-run memory hits


class ResultTable(BaseModel):
    title: str
    entity: str | None
    columns: list[str]
    rows: list[dict[str, Any]]


class FinalResult(BaseModel):
    status: Literal["completed", "needs_attention", "rejected", "failed", "needs_clarification"]
    headline: str
    summary_lines: list[str]
    changes: list[EvidenceItem] = []
    results: list[ResultTable] = []
    metrics: dict[str, Any] = {}
    verification: VerificationResult | None = None


class RunOptions(BaseModel):
    auto_approve: bool = False
    approval_threshold: Literal["none", "low", "medium", "high"] = "medium"
    faults: list[FaultSpec] = []
    max_retries: int = Field(3, ge=0, le=5)
    backoff_base: float = Field(0.5, ge=0, le=10)
    scenario: str | None = None


RunStatus = Literal["running", "awaiting_approval", "verifying", "completed", "needs_attention",
                    "rejected", "failed", "needs_clarification"]


class AgentState(BaseModel):
    task_id: str
    run_id: str
    user_goal: str
    mode: str = "demo"
    model: str = "rules"
    options: RunOptions = Field(default_factory=RunOptions)

    normalized_goal: StructuredGoal | None = None
    plan: Plan | None = None
    plan_attempts: int = 0
    replans: int = 0
    plan_errors: list[str] = []
    replan_reason: str | None = None

    current_step: int = 0
    completed_steps: list[str] = []
    pending_steps: list[str] = []
    step_runs: dict[str, StepRun] = {}
    pending_call: PendingCall | None = None
    last_result: ToolResult | None = None
    last_call_id: str | None = None

    tool_calls: list[ToolCallRecord] = []
    observations: list[Observation] = []
    errors: list[ErrorRecord] = []
    retry_count: int = 0
    fault_hits: dict[str, int] = {}

    approval_required: bool = False
    approval_status: Literal["none", "pending", "approved", "rejected"] = "none"
    approvals: list[ApprovalInfo] = []

    memory: WorkingMemory = Field(default_factory=WorkingMemory)
    verification_results: list[VerificationResult] = []
    evidence: list[EvidenceItem] = []
    final_result: FinalResult | None = None
    status: RunStatus = "running"
    route: str = ""  # decision written by a node, read by the conditional edge after it
    started_at: str = Field(default_factory=now_iso)
