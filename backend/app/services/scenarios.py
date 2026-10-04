"""Reproducible demo scenarios. Faults are injected into the simulated environment,
not into the agent: the agent has to notice and handle them like real failures."""
from __future__ import annotations

from typing import Any

DEMO_GOAL = ("Find all unpaid invoices above ₹50,000, identify the associated customers, update their status "
             "to High Priority, and verify that the updates were successful.")

SCENARIOS: dict[str, dict[str, Any]] = {
    "standard": {
        "title": "Transient failure → retry",
        "description": "The first customer update hits a simulated database timeout. The agent classifies it as "
                       "transient, backs off, retries and continues. Human approval is required before writes.",
        "goal": DEMO_GOAL,
        "options": {"faults": [{"tool": "update_customer_status", "mode": "error", "times": 1,
                                "error": "Temporary database timeout", "error_code": "TIMEOUT"}]},
    },
    "lost_write": {
        "title": "Silent lost write → caught by verification",
        "description": "One update reports success but is silently not persisted. Only independent verification "
                       "can catch this; the agent re-applies the missing change and verifies again.",
        "goal": DEMO_GOAL,
        "options": {"faults": [{"tool": "update_customer_status", "mode": "lost_write", "times": 1,
                                "match": {"customer_id": 7}}]},
    },
    "browser": {
        "title": "Computer use: operate the CRM UI",
        "description": "The agent changes customer status by driving the CRM web UI in a headless browser. If the "
                       "UI is unreachable it falls back to the API tool. Verification still reads the database.",
        "goal": "Using the browser, find customers with open high-priority support tickets and mark them as At Risk.",
        "options": {},
    },
}
