"""recover_from_failure node: classify the failure and choose a bounded response.

Order of preference:
1. retryable error and attempts left  -> exponential backoff, retry the same call
2. tool has a declared fallback       -> switch to the alternative tool
3. failure is scoped to one item      -> stop that branch, continue with the rest
4. LLM plan and replans left          -> re-plan with the failure as context
5. otherwise                          -> abort safely and explain
"""
from __future__ import annotations

from typing import Any

from app.agent.runtime import AgentRuntime, fmt_call, updates
from app.agent.state import AgentState, ErrorRecord


def recover_from_failure(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    pc, res = s.pending_call, s.last_result
    assert pc is not None and res is not None and s.plan is not None
    step = next(st for st in s.plan.steps if st.id == pc.step_id)
    sr = s.step_runs[step.id]
    tool = rt.registry.get(pc.tool)
    code = res.error_code.value if res.error_code else "UNKNOWN"
    max_attempts = s.options.max_retries + 1
    err = ErrorRecord(step_id=step.id, item_index=pc.item_index, tool=pc.tool, error=res.error or "", error_code=code,
                      retryable=res.retryable, attempt=pc.attempt)
    common = {"node": "recover_from_failure", "step_id": step.id, "tool": pc.tool, "error_code": code}

    if res.retryable and pc.attempt < max_attempts:
        delay = round(s.options.backoff_base * 2 ** (pc.attempt - 1), 3)
        err.resolution = f"retry {pc.attempt}/{s.options.max_retries} after {delay}s backoff"
        rt.emit(s, "retry", status="warning", attempt=pc.attempt + 1, delay_s=delay,
                title=f"Classified [{code}] as transient — retrying in {delay}s "
                      f"(retry {pc.attempt} of {s.options.max_retries})", **common)
        rt.sleep(delay)
        pc.attempt += 1
        s.retry_count += 1
        s.route = "retry"
    elif tool.fallback_tool and pc.original_tool is None and rt.registry.has(tool.fallback_tool):
        fb = rt.registry.get(tool.fallback_tool)
        pc.original_tool, pc.tool, pc.attempt = pc.tool, fb.name, 1
        pc.args = {k: v for k, v in pc.args.items() if k in fb.input_model.model_fields}
        err.resolution = f"switched to fallback tool {fb.name}"
        rt.emit(s, "recovery", status="warning",
                title=f"{pc.original_tool} failed ([{code}] {res.error}); trying alternative {fb.name}", **common)
        s.route = "retry"
    elif pc.item_index is not None:
        why = "retries exhausted" if res.retryable else "non-retryable error"
        label = (sr.items or [{}])[pc.item_index]
        label = label.get("company") or label.get("subject") or label.get("id") if isinstance(label, dict) else label
        sr.item_status[pc.item_index] = "failed"
        sr.item_index = pc.item_index + 1
        sr.notes.append(f"{label}: {res.error} ({why}); branch stopped")
        err.resolution = f"{why}; skipped this record and continued with the rest"
        rt.emit(s, "recovery", status="error",
                title=f"Stopped branch for {label}: [{code}] {res.error} ({why}). Continuing with remaining records.",
                **common)
        s.pending_call = None
        s.route = "continue"
    elif s.plan.source == "llm" and not rt.llm.is_demo and s.replans < rt.settings.max_replans:
        s.replans += 1
        s.replan_reason = f"step {step.id} {fmt_call(pc.tool, pc.args)} failed: [{code}] {res.error}"
        err.resolution = "re-planning"
        rt.emit(s, "recovery", status="warning", title=f"Step failed ([{code}] {res.error}); re-planning", **common)
        s.pending_call = None
        s.route = "replan"
    else:
        sr.status = "failed"
        s.status = "failed"
        err.resolution = "aborted: no safe recovery available"
        rt.emit(s, "recovery", status="error",
                title=f"Cannot recover from [{code}] {res.error} in step {step.id}; stopping safely", **common)
        s.route = "abort"

    s.errors.append(err)
    rt.audit(s, "recover_from_failure", tool=pc.tool, input={"error": res.error, "code": code, "attempt": err.attempt},
             output={"resolution": err.resolution}, status="info")
    return updates(s)
