"""Test configuration: an isolated temp database, no real LLM, no backoff sleeping."""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="centralign-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP}/test.db".replace("\\", "/"),
    "CHECKPOINT_DB_PATH": os.path.join(_TMP, "checkpoints.db"),
    "DATA_DIR": _TMP,
    "LLM_PROVIDER": "demo",
    "LLM_API_KEY": "",
    "BROWSER_TOOLS_ENABLED": "false",
    # Nothing listens here, so the browser tool fails fast and recovery must fall back.
    "FRONTEND_URL": "http://127.0.0.1:9",
})

import pytest  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app.agent.graph import make_serde  # noqa: E402
from app.database.seed import reseed  # noqa: E402
from app.database.session import init_db, session_scope  # noqa: E402
from app.services.task_service import RunManager, set_manager  # noqa: E402

init_db()


@pytest.fixture
def tmp_dir() -> str:
    return _TMP


@pytest.fixture(autouse=True)
def fresh_crm():
    with session_scope() as db:
        reseed(db)
    yield


class SleepRecorder(list):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


@pytest.fixture
def sleeps() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def manager(sleeps: SleepRecorder) -> RunManager:
    m = RunManager(checkpointer=InMemorySaver(serde=make_serde()), sleep=sleeps)
    set_manager(m)
    yield m
    set_manager(None)


def run_task(manager: RunManager, goal: str, **options):
    """Run synchronously; returns (run_id, state). Stops at an approval interrupt."""
    task = manager.create_task(goal, options)
    run_id = manager.start_run(task.id, background=False)
    return run_id, manager.state(run_id)
