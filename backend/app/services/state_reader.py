"""Read-only access to ground truth, deliberately separate from the tool layer.

The verifier and approval previews use this instead of the tools that made the
changes, so a buggy or lying tool cannot vouch for itself.
"""
from __future__ import annotations

from typing import Any

from app.database.models import Activity, Customer, OutboxMessage, SupportTicket
from app.database.session import SessionLocal

_MODELS = {"customer": Customer, "ticket": SupportTicket, "activity": Activity, "outbox": OutboxMessage}


class StateReader:
    def read_field(self, entity: str, entity_id: int, field: str) -> tuple[bool, Any]:
        """Returns (exists, value) using a brand-new session (no cached identity map)."""
        db = SessionLocal()
        try:
            row = db.get(_MODELS[entity], entity_id)
            return (row is not None, getattr(row, field) if row is not None else None)
        finally:
            db.close()

    def label(self, entity: str, entity_id: int) -> str | None:
        db = SessionLocal()
        try:
            row = db.get(_MODELS[entity], entity_id)
            if row is None:
                return None
            return row.company if entity == "customer" else getattr(row, "subject", None)
        finally:
            db.close()

    def exists(self, entity: str, entity_id: int) -> bool:
        return self.read_field(entity, entity_id, "id")[0]
