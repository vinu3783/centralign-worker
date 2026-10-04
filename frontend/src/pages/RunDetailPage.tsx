import { useParams } from "react-router-dom";
import { AuditTable } from "../components/AuditTable";
import { RunView } from "../components/run/RunView";
import { Card, PageHeader, StatCard, StatusBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { dateTime, duration } from "../services/format";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { data: run, reload } = useApi(() => api.run(runId), [runId]);
  const audit = useApi(() => api.runAudit(runId), [runId]);
  const m = run?.metrics ?? {};

  return (
    <>
      <PageHeader title={run?.goal ?? "Run"}
        subtitle={run && <span className="flex flex-wrap items-center gap-2"><StatusBadge value={run.status} /> <code>{run.id}</code> · started {dateTime(run.started_at)} · {run.mode === "demo" ? "DEMO mode" : run.model}</span>} />
      {run?.final_result && (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8" data-testid="run-metrics">
          <StatCard label="Total run time" value={duration(m.duration_ms)} hint={m.approval_wait_ms ? `${duration(m.approval_wait_ms)} awaiting approval` : undefined} />
          <StatCard label="Tool calls" value={m.tool_calls ?? 0} />
          <StatCard label="Successful" value={m.successful_calls ?? 0} />
          <StatCard label="Failed" value={m.failed_calls ?? 0} />
          <StatCard label="Retries" value={m.retries ?? 0} />
          <StatCard label="Recovered" value={m.recovered_failures ?? 0} />
          <StatCard label="Approvals" value={m.approvals_requested ?? 0} />
          <StatCard label="Verification" value={m.verification ? m.verification.toUpperCase() : "—"} />
        </div>
      )}
      <RunView runId={runId} onFinished={() => { void reload(); void audit.reload(); }} />
      <Card title="Audit log" className="mt-5" bodyClass="p-0">
        <AuditTable rows={audit.data} loading={audit.loading} />
      </Card>
    </>
  );
}
