"""Sandboxed file tool: writes reports only inside the configured reports directory."""
from __future__ import annotations

import csv
from typing import Any

from pydantic import Field

from app.tools.base import ErrorCode, StrictInput, Tool, ToolContext, ToolError, ToolResult


class ExportReportInput(StrictInput):
    # A bare file stem: no separators, no traversal, no extension games.
    filename: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    rows: list[dict[str, Any]] = Field(max_length=2000)
    columns: list[str] | None = Field(None, max_length=30)


class ExportReport(Tool):
    name = "export_report"
    description = "Write rows from a previous step to a CSV report in the sandboxed reports folder."
    input_model = ExportReportInput
    kind = "write"
    channel = "file"
    entity = "report"

    def execute(self, args: ExportReportInput, ctx: ToolContext) -> ToolResult:
        reports = ctx.settings.reports_dir.resolve()
        reports.mkdir(parents=True, exist_ok=True)
        stem = f"{args.filename}-{ctx.run_id}" if ctx.run_id else args.filename
        path = (reports / f"{stem}.csv").resolve()
        if path.parent != reports:  # defence in depth; the regex already forbids this
            raise ToolError(ErrorCode.VALIDATION, "Report path escapes the sandbox")
        columns = args.columns or (list(args.rows[0].keys()) if args.rows else [])
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(args.rows)
        return self.ok({"file": path.name, "rows": len(args.rows), "columns": columns,
                        "url": f"/api/files/reports/{path.name}"})


FILE_TOOLS: list[Tool] = [ExportReport()]
