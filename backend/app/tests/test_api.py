"""HTTP + WebSocket API."""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.task_service import wait_for_status


@pytest.fixture
def client(manager):
    with TestClient(create_app()) as c:
        yield c


def test_crm_endpoints(client):
    assert len(client.get("/api/customers").json()) == 16
    assert len(client.get("/api/invoices", params={"status": "unpaid", "min_amount": 50000}).json()) == 4
    assert [c["id"] for c in client.get("/api/customers", params={"q": "#9"}).json()] == [9]
    assert client.get("/api/invoices", params={"status": "nope"}).status_code == 422
    detail = client.get("/api/customers/9").json()
    assert len(detail["invoices"]) == 3 and len(detail["tickets"]) == 2


def test_patch_customer_records_activity_with_actor(client):
    r = client.patch("/api/customers/4", json={"status": "At Risk"}, headers={"X-Actor": "qa@example.com"})
    assert r.status_code == 200 and r.json()["status"] == "At Risk"
    act = client.get("/api/activity", params={"customer_id": 4}).json()[0]
    assert act["actor"] == "qa@example.com" and "Active → At Risk" in act["action"]
    assert client.patch("/api/customers/4", json={"status": "Gold"}).status_code == 422
    assert client.patch("/api/customers/999", json={"status": "Active"}).status_code == 404


def test_task_run_approval_and_stream_over_http(client):
    task = client.post("/api/tasks", json={"goal": "Find unpaid invoices above ₹50,000 and mark their customers as High Priority.",
                                           "run": True}).json()
    run_id = task["run_id"]
    wait_for_status(run_id, {"awaiting_approval"})
    assert client.post(f"/api/runs/{run_id}/approve", json={"by": "api-test"}).status_code == 200
    assert client.post(f"/api/runs/{run_id}/approve").status_code == 409  # no longer pending
    wait_for_status(run_id, {"completed"})

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["final_result"]["status"] == "completed" and detail["verification_passed"] is True
    assert detail["approvals"][0]["decided_by"] == "api-test"
    assert len([e for e in detail["evidence"] if e["kind"] == "change"]) == 4

    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        seen = [ws.receive_json() for _ in range(5)]
    assert [e["seq"] for e in seen] == [1, 2, 3, 4, 5] and seen[0]["type"] == "run_started"
    assert client.get(f"/api/runs/{run_id}/events", params={"after": 5}).json()[0]["seq"] == 6
    assert len(client.get(f"/api/runs/{run_id}/audit").json()) > 5
    stats = client.get("/api/stats").json()
    assert stats["tasks_completed"] >= 1 and stats["crm"]["high_priority"] == 4


def test_demo_scenarios_and_reset(client):
    ids = [s["id"] for s in client.get("/api/demo/scenarios").json()]
    assert {"standard", "lost_write", "browser"} <= set(ids)
    run_id = client.post("/api/demo/run", json={"scenario": "standard", "auto_approve": True}).json()["run_id"]
    wait_for_status(run_id, {"completed"})
    assert client.get("/api/runs/" + run_id).json()["metrics"]["retries"] == 1
    assert client.post("/api/admin/reset").json() == {"status": "reset"}
    assert client.get("/api/customers/1").json()["status"] == "Active"


def test_file_endpoint_blocks_traversal(client):
    assert client.get("/api/files/reports/..%2F..%2Fsecrets").status_code == 404
    assert client.get("/api/files/etc/passwd").status_code == 404
