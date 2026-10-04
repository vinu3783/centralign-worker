"""Pure data-transformation tools over records produced by earlier steps."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.tools.base import ErrorCode, StrictInput, Tool, ToolContext, ToolError, ToolResult


class GroupRecordsInput(StrictInput):
    records: list[dict[str, Any]] = Field(max_length=2000)
    by: str = Field(min_length=1, max_length=60, pattern=r"^[a-z_]+$")
    min_count: int = Field(1, ge=1, description="Keep only groups with at least this many records.")
    sum_field: str | None = Field(None, pattern=r"^[a-z_]+$")


class GroupRecords(Tool):
    name = "group_records"
    description = ("Group records from a previous step by a field (e.g. invoices by customer_id) and keep groups "
                   "with at least min_count records. Output: [{key, count, record_ids, label, total}].")
    input_model = GroupRecordsInput
    kind = "compute"
    channel = "compute"
    output_fields = ["key", "count", "record_ids", "label", "total"]

    def execute(self, args: GroupRecordsInput, ctx: ToolContext) -> ToolResult:
        groups: dict[Any, list[dict[str, Any]]] = {}
        for rec in args.records:
            if args.by not in rec:
                raise ToolError(ErrorCode.VALIDATION, f"Record has no field '{args.by}'")
            groups.setdefault(rec[args.by], []).append(rec)
        out = []
        for key, recs in groups.items():
            if len(recs) < args.min_count:
                continue
            item: dict[str, Any] = {"key": key, "count": len(recs), "record_ids": [r.get("id") for r in recs],
                                    "label": recs[0].get("customer_name")}
            if args.sum_field:
                item["total"] = round(sum(float(r.get(args.sum_field) or 0) for r in recs), 2)
            out.append(item)
        return self.ok(out, groups_total=len(groups))


COMPUTE_TOOLS: list[Tool] = [GroupRecords()]
