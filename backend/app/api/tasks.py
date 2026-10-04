from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.database.models import Run, Task
from app.database.session import session_scope
from app.schemas.task import DemoRunIn, TaskCreate, TaskOut
from app.services.scenarios import SCENARIOS
from app.services.task_service import get_manager

router = APIRouter(prefix="/api", tags=["tasks"])


def _task_out(task: Task, run_id: str | None = None) -> TaskOut:
    return TaskOut(id=task.id, goal=task.goal, options=task.options, created_at=task.created_at, run_id=run_id)


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate) -> TaskOut:
    manager = get_manager()
    task = manager.create_task(body.goal, body.options.model_dump(exclude_none=True))
    run_id = manager.start_run(task.id) if body.run else None
    return _task_out(task, run_id)


@router.get("/tasks")
def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as db:
        tasks = db.scalars(select(Task).order_by(Task.created_at.desc()).limit(limit)).all()
        return [_task_out(t).model_dump(mode="json") for t in tasks]


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    with session_scope() as db:
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "Task not found")
        runs = db.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.started_at.desc())).all()
        return {**_task_out(task).model_dump(mode="json"),
                "runs": [{"id": r.id, "status": r.status, "started_at": r.started_at.isoformat()} for r in runs]}


@router.post("/tasks/{task_id}/run")
def run_task(task_id: str) -> dict[str, str]:
    try:
        return {"run_id": get_manager().start_run(task_id)}
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc


@router.get("/demo/scenarios")
def scenarios() -> list[dict[str, Any]]:
    return [{"id": k, "title": v["title"], "description": v["description"], "goal": v["goal"]}
            for k, v in SCENARIOS.items()]


@router.post("/demo/run", response_model=TaskOut, status_code=201)
def run_demo(body: DemoRunIn) -> TaskOut:
    sc = SCENARIOS.get(body.scenario)
    if sc is None:
        raise HTTPException(404, f"Unknown scenario '{body.scenario}'")
    manager = get_manager()
    task = manager.create_task(sc["goal"], {**sc["options"], "auto_approve": body.auto_approve,
                                            "scenario": body.scenario})
    return _task_out(task, manager.start_run(task.id))
