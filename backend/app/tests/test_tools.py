"""Tool schemas, CRM tool behaviour, fault injection, approval policy."""
import pytest

from app.services.state_reader import StateReader
from app.tools.base import ErrorCode, RiskLevel, ToolContext
from app.tools.tool_registry import FaultInjector, FaultSpec, get_registry, requires_approval

REG = get_registry()
CTX = ToolContext(run_id="test")


def run(name, **args):
    return REG.execute(name, args, CTX).result


def test_every_tool_exposes_contract():
    for spec in REG.catalog():
        assert {"name", "description", "input_schema", "risk_level"} <= spec.keys()
        assert spec["risk_level"] in ("low", "medium", "high")


def test_unknown_tool_and_extra_args_are_rejected():
    assert run("exec_python", code="1").error_code == ErrorCode.UNKNOWN_TOOL
    r = run("search_invoices", status="unpaid", sql="1=1")
    assert not r.success and r.error_code == ErrorCode.VALIDATION and not r.retryable


def test_invalid_enum_rejected():
    r = run("update_customer_status", customer_id=1, status="Super VIP")
    assert r.error_code == ErrorCode.VALIDATION


def test_invoice_filter_excludes_boundary():
    r = run("search_invoices", status="unpaid", amount_gt=50000)
    assert r.success and r.metadata["count"] == 4
    assert all(i["amount"] > 50000 and i["status"] == "unpaid" for i in r.data)
    assert 50000.0 not in [i["amount"] for i in r.data]  # Delta Foods' invoice is exactly 50,000


def test_update_customer_status_writes_and_logs_activity():
    r = run("update_customer_status", customer_id=3, status="High Priority")
    assert r.success and r.data["before"] == "Active" and r.data["changed"]
    assert StateReader().read_field("customer", 3, "status") == (True, "High Priority")
    acts = run("get_activity", customer_id=3).data
    assert acts[0]["actor"] == "CentrAlign Worker" and acts[0]["metadata"]["run_id"] == "test"
    again = run("update_customer_status", customer_id=3, status="High Priority")
    assert again.success and again.data["changed"] is False


def test_missing_customer_is_not_retryable():
    r = run("update_customer_status", customer_id=999, status="At Risk")
    assert r.error_code == ErrorCode.NOT_FOUND and not r.retryable


def test_group_records():
    invoices = run("search_invoices", status="overdue").data
    groups = run("group_records", records=invoices, by="customer_id", min_count=2, sum_field="amount").data
    assert sorted(g["key"] for g in groups) == [5, 8, 9]


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b", "x.csv", ""])
def test_export_report_filename_sandbox(name):
    assert run("export_report", filename=name, rows=[]).error_code == ErrorCode.VALIDATION


def test_export_report_writes_inside_reports_dir(tmp_dir):
    r = run("export_report", filename="ok-report", rows=[{"a": 1}, {"a": 2}])
    assert r.success and r.data["rows"] == 2


def test_fault_injection_error_then_success():
    faults = FaultInjector([FaultSpec(tool="update_customer_status", times=1)])
    args = {"customer_id": 1, "status": "At Risk"}
    first = REG.execute("update_customer_status", args, CTX, faults)
    assert not first.result.success and first.result.retryable and first.injected_fault
    assert StateReader().read_field("customer", 1, "status")[1] == "Active"  # nothing written
    second = REG.execute("update_customer_status", args, CTX, faults)
    assert second.result.success


def test_fault_injection_lost_write_reports_success_but_does_not_persist():
    faults = FaultInjector([FaultSpec(tool="update_customer_status", mode="lost_write")])
    ex = REG.execute("update_customer_status", {"customer_id": 1, "status": "At Risk"}, CTX, faults)
    assert ex.result.success
    assert StateReader().read_field("customer", 1, "status")[1] == "Active"


def test_fault_match_targets_specific_args():
    faults = FaultInjector([FaultSpec(tool="get_customer", match={"customer_id": 2})])
    assert faults.take("get_customer", {"customer_id": 1}) is None
    assert faults.take("get_customer", {"customer_id": 2}) is not None


@pytest.mark.parametrize("risk,threshold,expected", [
    (RiskLevel.MEDIUM, "medium", True), (RiskLevel.HIGH, "medium", True), (RiskLevel.LOW, "medium", False),
    (RiskLevel.MEDIUM, "high", False), (RiskLevel.HIGH, "none", False),
])
def test_approval_policy(risk, threshold, expected):
    assert requires_approval(risk, threshold) is expected
