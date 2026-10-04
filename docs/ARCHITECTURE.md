# CentrAlign Worker: architecture

This document explains how the agent is built and why. For setup and the demo, see the [README](../README.md).

## 1. Agent state

All agent knowledge lives in one typed Pydantic model, `AgentState` (`backend/app/agent/state.py`). It is LangGraph's state schema and is checkpointed after every node. Nothing is kept in globals.

| Group | Fields |
|---|---|
| Identity / config | `task_id`, `run_id`, `user_goal`, `mode`, `model`, `options` (approval threshold, retry budget, backoff, injected faults) |
| Understanding / planning | `normalized_goal: StructuredGoal`, `plan: Plan`, `plan_attempts`, `replans`, `plan_errors`, `replan_reason` |
| Progress | `current_step`, `completed_steps`, `pending_steps`, `step_runs: dict[step_id, StepRun]`, `pending_call: PendingCall` |
| Execution record | `tool_calls: list[ToolCallRecord]`, `last_result`, `observations`, `errors: list[ErrorRecord]`, `retry_count`, `fault_hits` |
| Human-in-the-loop | `approval_required`, `approval_status`, `approvals: list[ApprovalInfo]` |
| Outcome | `verification_results`, `evidence: list[EvidenceItem]`, `final_result: FinalResult`, `status` |
| Memory | `memory: WorkingMemory` (records seen per entity, actions, failures, approvals, recalled cross-run memories) |
| Control | `route`: the decision a node writes for the conditional edge after it |

`StepRun` tracks per-step execution: the resolved `items` of a `for_each` step, a per-item status (`pending | succeeded | failed | compliant`), outputs, the approval decision, and the ground-truth preview of the records it will change.

Every node follows the same pattern: deep-copy the state, mutate the copy, and return all fields. Nodes are therefore pure functions of `(state, runtime)` plus their logged side effects, which keeps them easy to test and to resume.

## 2. Graph design

`backend/app/agent/graph.py` wires 13 nodes:

```
understand_goal ─► create_plan ─► validate_plan ─► select_tool ─┬─► execute_action ─► observe_result ─► evaluate_result
       │                ▲              │                         ├─► request_approval ─► await_approval (interrupt)
       ▼                └── invalid ───┘                         ├─► verify_outcome ─► generate_summary ─► complete
 generate_summary                                                └─► recover_from_failure
```

Conditional routing (`route` values):

| From | Routes |
|---|---|
| `understand_goal` | `plan`, `clarify` |
| `validate_plan` | `execute`, `replan` (up to 3 plan attempts), `abort` |
| `select_tool` | `execute`, `approval`, `verify`, `failure` |
| `await_approval` | `approved` → `select_tool`, `rejected` → summary |
| `evaluate_result` | `next` → `select_tool`, `recover` |
| `recover_from_failure` | `retry` → `execute_action`, `continue` → `select_tool`, `replan` → `create_plan`, `abort` → summary |
| `verify_outcome` | `pass`, `fail` → summary, `remediate` → `select_tool` |

**Granularity: one tool call per pass.** `select_tool` walks the plan, resolves references, and prepares exactly one call. A `for_each` step over 4 customers therefore makes 4 passes through execute → observe → evaluate. Each retry is its own pass too. This keeps the timeline faithful, gives every attempt its own audit row and checkpoint, and lets recovery act on a single call.

**Plans and references.** A step is `{id, tool, args, for_each?, items?, expect?}`. Arguments can reference earlier outputs:

```
$s1.data[*].customer_id|unique     distinct values from step s1's records
$s2.data                           s2's records (as a for_each source)
$item.id                           the current for_each item's field
```

`refs.py` resolves these over plain dicts with a regex tokenizer (`.field`, `[*]`, `[n]`, `|unique`). There is no `eval` and no attribute access on Python objects.

**Planning paths.**
- *DEMO mode:* `rule_parser.parse_goal` (a compositional grammar for entities, conditions, grouping, actions and channel) followed by `planner.compile_plan` (goal → search primary entity → optional `group_records` → resolve customers → one `for_each` step per action).
- *LLM mode:* the LLM returns `StructuredGoal` JSON (validated by `check_goal`: field names and enum values), then `Plan` JSON built from the live tool catalog. Invalid output is fed back once at the provider level, and validator errors are fed back at the graph level. If the LLM fails, the app falls back to the rule compiler and says so in the timeline.

Both paths produce the same types and pass through the same `validate_plan`. In LLM mode, `ground_actions` keeps only actions backed by an exact, type-appropriate quote from the request. `validate_plan(plan, registry, max_steps, goal)` also checks the plan against the goal: write steps must match goal actions, every goal entity must be touched, and every goal condition must be applied as a filter (using each tool's `filter_semantics`). See the README's "Guarding against LLM mistakes" for the failures these checks were built from.

## 3. Tool registry

`tools/base.py` defines the contract and `tools/tool_registry.py` the allowlist.

```python
class Tool:
    name, description, input_model (Pydantic, extra="forbid"), risk_level (LOW|MEDIUM|HIGH)
    kind ("read"|"compute"|"write"), channel ("api"|"browser"|"file"|"compute"), entity
    fallback_tool        # equivalent tool to try if this one fails non-retryably
    filter_semantics     # arg -> (record field, operator), used by the verifier
    execute(args, ctx) -> ToolResult{success, tool, data, metadata, error, error_code, retryable}
    mutation_target(args) -> MutationTarget{entity, entity_id, field, desired} | None
```

| Tool | Channel | Risk |
|---|---|---|
| `search_invoices`, `get_invoice`, `search_customers`, `get_customer`, `search_tickets`, `get_activity` | api/db | LOW |
| `group_records` | compute | LOW |
| `record_activity` (append-only note) | api/db | LOW |
| `update_customer_status`, `update_ticket_priority` | api/db | MEDIUM |
| `send_customer_email` (simulated outbox) | api/db | HIGH |
| `export_report` (sandboxed CSV) | file | LOW |
| `browser_read_table`, `browser_update_customer_status` (→ fallback `update_customer_status`) | browser | LOW / MEDIUM |

`ToolRegistry.execute` is the single choke point. It looks up the tool (unknown → `UNKNOWN_TOOL`), validates the arguments (`VALIDATION`), consults the **fault injector**, runs the tool, and maps exceptions (`OperationalError` → retryable `TIMEOUT`, anything else → `INTERNAL`). A tool can never crash the agent loop.

The agent loop does not know which channel a tool uses. Browser, API, file and compute tools are interchangeable behind the same contract. Business logic lives in one place: the CRM REST API's list endpoints call the same search tools, and the status-change function is shared by the tool and the PATCH endpoint.

## 4. Safety model

1. The LLM output is **data** (JSON validated into Pydantic models), never code.
2. **Plan validation** before execution: tools must be in the allowlist, argument names must exist in the schema, required arguments must be present, references must point backwards, `$item` may only appear in `for_each` steps, and plans have a size cap. Literal arguments are fully schema-validated.
3. **Call-time validation** after references are resolved (strict schemas, enums and ranges).
4. **Risk-gated approval** for writes at or above the threshold, with a ground-truth preview. If goal understanding reported an ambiguity, approval is required even when the run is set to auto-approve.
5. **No escape hatches:** no shell, SQL, eval or arbitrary-URL tools. The file tool is restricted to a sandbox. The browser tool only navigates to the configured CRM UI.
6. **Bounded autonomy:** max 3 retries, 1 fallback, 1 re-plan, 1 remediation, 3 plan attempts, and a graph recursion limit.
7. **Auditability:** every node decision and tool call goes to `audit_logs` (secrets scrubbed, payloads capped). Every UI-visible event is persisted to `run_events`.
8. **Checkpoint deserialization** is allowlisted to the app's own types.

## 5. Memory

- **Working memory (within a run):** `WorkingMemory` keeps the latest version of every invoice, customer or ticket seen (by ID), plus action, failure and approval logs. Step outputs and per-item statuses in `step_runs` act as the agent's scratchpad for references.
- **Cross-run memory (SQLite `agent_memory`):** structured rows, no embeddings.
  - `task_outcome` is keyed by a goal signature (a hash of entity, conditions, grouping and actions). On a repeat goal the agent says *"I've handled this goal N times; last run ended 'completed' with 4 records changed."*
  - `tool_reliability` counts transient failures per tool. During planning the agent notes that retries are armed for tools with a history of flakiness.

## 6. Retry strategy

| Error code | Retryable | Response |
|---|---|---|
| `TIMEOUT`, `RATE_LIMITED`, `UNAVAILABLE` | yes | exponential backoff `base × 2^(attempt−1)` (0.5, 1, 2 s), max 3 retries |
| `UNAVAILABLE` (connection refused, browser) | no | fallback tool if declared |
| `NOT_FOUND`, `VALIDATION`, `CONFLICT`, `UNKNOWN_TOOL`, `INTERNAL` | no | stop that branch (for_each item) / re-plan (LLM) / abort |

After retries are exhausted, the item is marked failed and the run continues with the remaining items. Verification then reports the gap, and remediation is attempted once only if the cause was transient. The sleep function is injected, so tests assert the exact backoff schedule without waiting.

## 7. Verification strategy

`verify_outcome` runs after the plan completes and is independent of execution:

1. **Record-state checks:** the targets are re-derived from the plan (resolved arguments → `mutation_target`). They include records that failed or were skipped as compliant, so "expected 4, observed 3" is visible. Values are re-read through `StateReader`, which opens a new SQLAlchemy session so no cached identity map or tool state is involved.
2. **Filter conformance:** every record a search step returned is checked against that step's filters using `filter_semantics`. This catches query bugs.
3. **Re-query consistency:** read steps are re-executed and their ID sets compared, unless the run modified a field the query filters on.
4. **Artifact checks:** outbox rows and CSV files exist with the expected row counts.

A FAIL with remediable mismatches (lost write, or retryable errors that ran out of retries) appends a remediation step that inherits the original approval. Verification then runs again. Evidence items are marked `verified` per record, and a superseded lost write stays `verified=False` as a permanent record of what happened.

A run is `completed` only if verification passed **and** at least one record matched when the goal asked for changes. Otherwise it is `needs_attention`.

## 8. Human approval

`select_tool` decides whether a write step needs approval (`requires_approval(tool.risk, threshold)`; per-run `auto_approve` exists for tests and unattended runs and is recorded as `auto_approved`). `request_approval` writes the `approvals` row and the event exactly once. `await_approval` contains only `interrupt()`, because LangGraph re-runs the interrupted node on resume and side effects before the interrupt would otherwise be duplicated.

`POST /api/runs/{id}/approve|reject` validates that an approval is pending and the run is not executing, records the decision, and resumes the graph with `Command(resume={...})` on a worker thread. The SQLite checkpointer makes pending approvals durable across restarts. Runs that were mid-execution during a restart are marked failed rather than resumed blindly.

## 9. API architecture

```
FastAPI
├── /api/customers, /api/invoices, /api/tickets, /api/activity, /api/outbox     CRM (UI + browser tool)
├── /api/tasks (POST: create [+run]), /api/tasks/{id}, /api/tasks/{id}/run
├── /api/demo/scenarios, /api/demo/run
├── /api/runs, /api/runs/{id} (detail + live state snapshot), /api/runs/{id}/events, /api/runs/{id}/audit
├── /api/runs/{id}/approve, /api/runs/{id}/reject, /api/approvals
├── WS /api/runs/{id}/ws                                                          live event stream
└── /api/system, /api/tools, /api/stats, /api/audit, /api/admin/reset, /api/files/{reports|screenshots}/{name}
```

**Execution model:** `RunManager` (`services/task_service.py`) compiles the graph once and runs each run (and each resume) on a daemon thread.

**Event stream:** `EventBus.publish` persists each event to `run_events` with a per-run sequence number, then pushes it to subscriber asyncio queues via `loop.call_soon_threadsafe`. The WebSocket handler subscribes first, replays history after `?after=seq`, then streams live events and de-duplicates by `seq`. Late joiners and reconnects therefore never miss or double events.

## 10. Frontend architecture

- `services/api.ts`: a typed fetch client. `types/index.ts` mirrors the backend schemas.
- `hooks/useRunStream.ts`: WebSocket with replay (`after=lastSeq`), backoff reconnect, and a polling fallback. `useLiveRun` refetches the run detail (debounced) whenever events arrive.
- `components/run/`: `PhaseStepper` (GOAL→…→COMPLETE driven by event phases), `Timeline` (merges a tool call's running and finished events; expandable input/output JSON), `GoalCard`, `PlanCard` (live per-step progress), `ApprovalCard` (current → proposed preview, approve/reject), `StatusCard`, and `ResultPanel` (headline, verification checks, evidence table, result tables).
- CRM pages use a shared `DataTable` exposing `data-testid` / `data-loading` hooks, which both Playwright tests and the agent's browser tool use to wait for real data.

## 11. Scalability considerations

| Concern | Prototype | Production path |
|---|---|---|
| Database | SQLite (WAL) via SQLAlchemy | `DATABASE_URL=postgresql+psycopg://…`. Models use portable types (JSON, a UTC-aware datetime type) |
| Checkpoints | `SqliteSaver` | `PostgresSaver` (same interface) |
| Execution | Threads in the API process | Job queue (Celery/Arq/Temporal) with workers. `RunManager.start_run` / `decide` become enqueue operations |
| Events | In-process fan-out + DB replay | Redis pub/sub or Postgres LISTEN/NOTIFY, keeping DB replay for late joiners |
| Browser tools | New Chromium per call | A pooled browser service with per-tenant contexts |
| LLM | Synchronous calls, temperature 0, JSON mode | Rate limiting, caching of goal → plan, model routing |
| Multi-tenancy | None | Tenant ID on every table and tool context, approval RBAC |

The agent itself does not change in any of these moves: the graph, nodes and tool contract stay the same.
