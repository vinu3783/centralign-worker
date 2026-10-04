"""Run event stream: persisted (for replay) and fanned out live to WebSocket subscribers.

The agent runs in worker threads; subscribers live on the asyncio loop, so
delivery uses loop.call_soon_threadsafe.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.database.models import RunEvent
from app.database.session import session_scope

log = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq: dict[str, int] = {}
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def publish(self, run_id: str, type: str, **payload: Any) -> dict[str, Any]:
        payload = _jsonable(payload)
        ts = datetime.now(timezone.utc)
        with self._lock:
            if run_id not in self._seq:
                with session_scope() as db:
                    self._seq[run_id] = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)) or 0
            self._seq[run_id] += 1
            seq = self._seq[run_id]
            with session_scope() as db:
                db.add(RunEvent(run_id=run_id, seq=seq, type=type, payload=payload, timestamp=ts))
            event = {"seq": seq, "run_id": run_id, "type": type, "timestamp": ts.isoformat(), **payload}
            subs = list(self._subs.get(run_id, ()))
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # loop closed
                pass
        log.info("[%s] %s %s", run_id, type, payload.get("title", ""))
        return event

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.setdefault(run_id, set()).add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subs[run_id] = {s for s in self._subs.get(run_id, set()) if s[1] is not queue}


def history(run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                          .order_by(RunEvent.seq)).all()
        return [{"seq": r.seq, "run_id": r.run_id, "type": r.type, "timestamp": r.timestamp.isoformat(),
                 **(r.payload or {})} for r in rows]


bus = EventBus()
