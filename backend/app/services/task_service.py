"""Task/run lifecycle: create tasks, run the agent graph on worker threads, resume on approval."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command
from sqlalchemy import select

from app.agent.graph import build_graph, make_checkpointer
from app.agent.llm import LLMProvider, build_provider
from app.agent.runtime import AgentRuntime
from app.agent.state import AgentState, RunOptions
from app.config import Settings, get_settings
from app.database.models import Run, Task
from app.database.session import session_scope
from app.services import run_store
from app.services.event_bus import bus
from app.tools.tool_registry import ToolRegistry, get_registry

log = logging.getLogger(__name__)
TERMINAL = {"completed", "needs_attention", "rejected", "failed", "needs_clarification"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class RunManager:
    def __init__(self, settings: Settings | None = None, *, registry: ToolRegistry | None = None,
                 llm: LLMProvider | None = None, checkpointer: Any = None, sleep: Any = None):
        self.settings = settings or get_settings()
        self.runtime = AgentRuntime(registry=registry or get_registry(), llm=llm or build_provider(self.settings),
                                    settings=self.settings, **({"sleep": sleep} if sleep is not None else {}))
        self.graph = build_graph(self.runtime, checkpointer or make_checkpointer(self.settings.checkpoint_db_path))
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- info
    @property
    def mode(self) -> str:
        return "demo" if self.runtime.llm.is_demo else "llm"

    @property
    def model_label(self) -> str:
        return self.runtime.llm.label

    # ---------------------------------------------------------------- tasks
    def create_task(self, goal: str, options: dict[str, Any] | None = None) -> Task:
        opts = self._options(options or {})
        with session_scope() as db:
            task = Task(id=_id("task"), goal=goal.strip(), options=opts.model_dump(mode="json"))
            db.add(task)
        return task

    def _options(self, raw: dict[str, Any]) -> RunOptions:
        base = {"approval_threshold": self.settings.approval_threshold, "max_retries": self.settings.max_retries,
                "backoff_base": self.settings.retry_backoff_base}
        return RunOptions.model_validate({**base, **{k: v for k, v in raw.items() if v is not None}})

    def start_run(self, task_id: str, *, background: bool = True) -> str:
        with session_scope() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise KeyError(task_id)
            run_id = _id("run")
            db.add(Run(id=run_id, task_id=task.id, goal=task.goal, status="running", mode=self.mode,
                       model=self.model_label))
            goal, options = task.goal, RunOptions.model_validate(task.options)
        state = AgentState(task_id=task_id, run_id=run_id, user_goal=goal, mode=self.mode, model=self.model_label,
                           options=options)
        bus.publish(run_id, "run_started", status="running", title="Run started", goal=goal, mode=self.mode,
                    model=self.model_label, options=options.model_dump(mode="json"))
        self._dispatch(run_id, state, background)
        return run_id

    def decide(self, run_id: str, approved: bool, by: str = "operator", comment: str | None = None,
               *, background: bool = True) -> None:
        with self._lock:
            appr = run_store.pending_approval(run_id)
            if appr is None:
                raise LookupError("This run has no pending approval")
            if self.is_running(run_id):
                raise RuntimeError("Run is still executing")
            run_store.decide_approval(appr.id, approved, by, comment)
        self._dispatch(run_id, Command(resume={"approved": approved, "by": by, "comment": comment}), background)

    # -------------------------------------------------------------- running
    def _dispatch(self, run_id: str, payload: Any, background: bool) -> None:
        if not background:
            self._invoke(run_id, payload)
            return
        t = threading.Thread(target=self._invoke, args=(run_id, payload), name=f"agent-{run_id}", daemon=True)
        with self._lock:
            self._threads[run_id] = t
        t.start()

    def _invoke(self, run_id: str, payload: Any) -> None:
        cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": 1000}
        try:
            self.graph.invoke(payload, cfg)
        except Exception as exc:  # the agent must never die silently
            log.exception("Run %s crashed", run_id)
            run_store.update_run(run_id, status="failed", error=f"Agent crashed: {exc}",
                                 finished_at=datetime.now(timezone.utc))
            bus.publish(run_id, "run_completed", status="error", final_status="failed",
                        title=f"Run crashed: {exc}")

    def is_running(self, run_id: str) -> bool:
        t = self._threads.get(run_id)
        return bool(t and t.is_alive() and t is not threading.current_thread())

    def wait(self, run_id: str, timeout: float = 30) -> None:
        t = self._threads.get(run_id)
        if t:
            t.join(timeout)

    def state(self, run_id: str) -> AgentState | None:
        snap = self.graph.get_state({"configurable": {"thread_id": run_id}})
        if not snap or not snap.values:
            return None
        values = snap.values
        return values if isinstance(values, AgentState) else AgentState.model_validate(values)

    def recover_orphans(self) -> None:
        """Runs that were mid-execution when the server stopped cannot be trusted to resume
        blindly; mark them failed. Runs awaiting approval stay resumable (checkpointed)."""
        with session_scope() as db:
            for run in db.scalars(select(Run).where(Run.status.in_(["running", "verifying"]))):
                run.status, run.error = "failed", "Server restarted while this run was executing"
                run.finished_at = datetime.now(timezone.utc)


_manager: RunManager | None = None


def get_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager


def set_manager(manager: RunManager | None) -> None:
    global _manager
    _manager = manager


def wait_for_status(run_id: str, statuses: set[str], timeout: float = 30) -> str:
    """Poll the run row until it reaches one of `statuses` (tests / scripts)."""
    deadline = time.time() + timeout
    status = ""
    while time.time() < deadline:
        with session_scope() as db:
            status = db.get(Run, run_id).status
        if status in statuses:
            return status
        time.sleep(0.05)
    raise TimeoutError(f"Run {run_id} stuck in {status}")
