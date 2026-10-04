"""The LangGraph state machine.

START → understand_goal → create_plan → validate_plan → select_tool ─┬→ execute_action → observe_result → evaluate_result ─┬→ select_tool (next)
                                                                    ├→ request_approval → await_approval ─┬→ select_tool    └→ recover_from_failure ─┬→ execute_action (retry / fallback)
                                                                    │                                      └→ generate_summary                      ├→ select_tool (skip branch)
                                                                    └→ verify_outcome ─┬→ generate_summary → complete → END                      ├→ create_plan (re-plan)
                                                                                       └→ select_tool (remediate)                                 └→ generate_summary (abort)
"""
from __future__ import annotations

import inspect
import sqlite3
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent import planner
from app.agent.approval import await_approval, request_approval
from app.agent.executor import execute_action, select_tool
from app.agent.observer import evaluate_result, observe_result
from app.agent.recovery import recover_from_failure
from app.agent.runtime import AgentRuntime, updates
from app.agent.state import AgentState, StepRun
from app.agent.summary import complete, generate_summary
from app.agent.verifier import verify_outcome
from app.services import memory_service, run_store


def understand_goal(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    rt.emit(s, "node", node="understand_goal", status="running", title="Understanding the goal",
            detail=s.user_goal, mode=s.mode, model=s.model)
    goal, source, notes = planner.interpret_goal(s.user_goal, rt.llm)
    s.normalized_goal = planner.ensure_objective(goal)
    for note in notes:
        rt.emit(s, "observation", node="understand_goal", status="warning", title=note)
    rt.audit(s, "understand_goal", input={"goal": s.user_goal}, output=goal.model_dump(mode="json"), status="success")
    run_store.update_run(s.run_id, structured_goal=goal)
    if goal.clarification_needed:
        s.status = "needs_clarification"
        rt.emit(s, "goal", node="understand_goal", status="warning", title="Goal needs clarification",
                detail=goal.clarification_needed, goal=goal, source=source)
        s.route = "clarify"
        return updates(s)
    s.memory.recalled = memory_service.recall(goal)
    rt.emit(s, "goal", node="understand_goal", status="success", title="Goal understood", detail=goal.objective,
            goal=goal, source=source)
    for amb in goal.ambiguities:
        rt.emit(s, "observation", node="understand_goal", status="warning", title=f"Ambiguity: {amb}")
    if s.memory.recalled:
        last = s.memory.recalled[0]
        rt.emit(s, "memory", node="understand_goal", status="info",
                title=f"I've handled this goal {len(s.memory.recalled)} time(s) before; last run {last['run_id']} "
                      f"ended '{last.get('status')}' with {last.get('records_changed', 0)} record(s) changed",
                recalled=s.memory.recalled)
    s.route = "plan"
    return updates(s)


def create_plan(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    assert s.normalized_goal is not None
    s.plan_attempts += 1
    title = "Re-planning" if s.replan_reason else ("Fixing the plan" if s.plan_errors else "Planning")
    rt.emit(s, "node", node="create_plan", status="running", title=title)
    plan, notes = planner.create_plan(s.normalized_goal, rt.llm, rt.registry, errors=s.plan_errors,
                                      replan_reason=s.replan_reason, attempt=s.plan_attempts)
    for note in notes:
        rt.emit(s, "observation", node="create_plan", status="warning", title=note)
    s.plan = plan
    s.current_step, s.step_runs, s.completed_steps = 0, {}, []
    s.pending_steps = [st.id for st in plan.steps]
    s.replan_reason = None
    flaky = memory_service.tool_reliability([st.tool for st in plan.steps])
    if flaky:
        rt.emit(s, "memory", node="create_plan", status="info",
                title="Memory: these tools had transient failures in past runs — retries are armed: "
                      + ", ".join(f"{t} ({n}×)" for t, n in flaky.items()))
    s.route = "validate"
    return updates(s)


def validate_plan(state: AgentState, rt: AgentRuntime) -> dict[str, Any]:
    s = state.model_copy(deep=True)
    assert s.plan is not None
    errors = planner.validate_plan(s.plan, rt.registry, rt.settings.max_plan_steps, s.normalized_goal)
    steps_view = []
    for st in s.plan.steps:
        tool = rt.registry.get(st.tool) if rt.registry.has(st.tool) else None
        steps_view.append({**st.model_dump(mode="json"), "risk": tool.risk_level.value if tool else None,
                           "kind": tool.kind if tool else None, "channel": tool.channel if tool else None})
    rt.audit(s, "validate_plan", input=s.plan.model_dump(mode="json"), output={"errors": errors},
             status="success" if not errors else "failed")
    if errors:
        s.plan_errors = errors
        rt.emit(s, "plan", node="validate_plan", status="error", title="Plan rejected by validator",
                errors=errors, steps=steps_view, source=s.plan.source)
        if s.plan_attempts < 3:
            s.route = "replan"
        else:
            s.status = "failed"
            s.route = "abort"
        return updates(s)
    s.plan_errors = []
    s.step_runs = {st.id: StepRun(step_id=st.id) for st in s.plan.steps}
    run_store.update_run(s.run_id, plan=s.plan)
    rt.emit(s, "plan", node="validate_plan", status="success",
            title=f"Plan generated and validated ({len(s.plan.steps)} steps, source: {s.plan.source})",
            steps=steps_view, rationale=s.plan.rationale, source=s.plan.source)
    s.route = "execute"
    return updates(s)


def _route(state: AgentState) -> str:
    return state.route


def build_graph(rt: AgentRuntime, checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(AgentState)
    nodes = {
        "understand_goal": understand_goal, "create_plan": create_plan, "validate_plan": validate_plan,
        "select_tool": select_tool, "request_approval": request_approval, "await_approval": await_approval,
        "execute_action": execute_action, "observe_result": observe_result, "evaluate_result": evaluate_result,
        "recover_from_failure": recover_from_failure, "verify_outcome": verify_outcome,
        "generate_summary": generate_summary, "complete": complete,
    }
    for name, fn in nodes.items():
        g.add_node(name, partial(fn, rt=rt))

    g.add_edge(START, "understand_goal")
    g.add_conditional_edges("understand_goal", _route, {"plan": "create_plan", "clarify": "generate_summary"})
    g.add_edge("create_plan", "validate_plan")
    g.add_conditional_edges("validate_plan", _route,
                            {"execute": "select_tool", "replan": "create_plan", "abort": "generate_summary"})
    g.add_conditional_edges("select_tool", _route, {"execute": "execute_action", "approval": "request_approval",
                                                    "verify": "verify_outcome", "failure": "recover_from_failure"})
    g.add_edge("request_approval", "await_approval")
    g.add_conditional_edges("await_approval", _route, {"approved": "select_tool", "rejected": "generate_summary"})
    g.add_edge("execute_action", "observe_result")
    g.add_edge("observe_result", "evaluate_result")
    g.add_conditional_edges("evaluate_result", _route, {"next": "select_tool", "recover": "recover_from_failure"})
    g.add_conditional_edges("recover_from_failure", _route, {"retry": "execute_action", "continue": "select_tool",
                                                             "replan": "create_plan", "abort": "generate_summary"})
    g.add_conditional_edges("verify_outcome", _route, {"pass": "generate_summary", "fail": "generate_summary",
                                                       "remediate": "select_tool"})
    g.add_edge("generate_summary", "complete")
    g.add_edge("complete", END)
    return g.compile(checkpointer=checkpointer)


def _checkpoint_allowlist() -> list[tuple[str, str]]:
    """Explicitly allow (only) our own state types to be deserialized from checkpoints."""
    from app.agent import state as state_mod
    from app.tools import base as base_mod, tool_registry as registry_mod

    allowed = []
    for mod in (state_mod, base_mod, registry_mod):
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and obj.__module__ == mod.__name__ and issubclass(obj, (BaseModel, Enum)):
                allowed.append((mod.__name__, name))
    return allowed


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_checkpoint_allowlist())


def make_checkpointer(path: str) -> SqliteSaver:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn, serde=make_serde())
