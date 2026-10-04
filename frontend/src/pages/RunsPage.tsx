import { useNavigate } from "react-router-dom";
import { DataTable } from "../components/DataTable";
import { Badge, ErrorBanner, PageHeader, StatusBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { duration, relative } from "../services/format";
import type { RunSummary } from "../types";

export function RunsTable({ rows, loading }: { rows: RunSummary[] | null; loading?: boolean }) {
  const navigate = useNavigate();
  return (
    <DataTable<RunSummary>
      rows={rows} loading={loading} empty="No runs yet — start one from the AI Worker page."
      onRowClick={(r) => navigate(`/runs/${r.id}`)} rowTestId={(r) => `run-row-${r.id}`}
      columns={[
        { key: "goal", header: "Task", render: (r) => <span className="line-clamp-2 max-w-md text-slate-900">{r.goal}</span> },
        { key: "status", header: "Status", render: (r) => <StatusBadge value={r.status} /> },
        { key: "duration", header: "Duration", align: "right", render: (r) => duration(r.metrics.duration_ms) },
        { key: "tools", header: "Tools used", render: (r) => <span className="text-xs text-slate-500">{(r.metrics.tools_used ?? []).length ? `${r.metrics.tool_calls} calls · ${(r.metrics.tools_used ?? []).length} tools` : "—"}</span> },
        { key: "retries", header: "Retries", align: "right", render: (r) => r.metrics.retries ?? 0 },
        { key: "verification", header: "Verification", render: (r) => r.verification_passed === null ? <span className="text-slate-400">—</span> : <Badge tone={r.verification_passed ? "green" : "red"}>{r.verification_passed ? "pass" : "fail"}</Badge> },
        { key: "started_at", header: "Started", render: (r) => <span className="text-xs text-slate-500">{relative(r.started_at)}</span> },
      ]}
    />
  );
}

export function RunsPage() {
  const { data, error, loading } = useApi(() => api.runs(100), []);
  return (
    <>
      <PageHeader title="Runs" subtitle="Every agent run, with its plan, tool calls, approvals, verification and evidence." />
      <ErrorBanner message={error} />
      <RunsTable rows={data} loading={loading} />
    </>
  );
}
