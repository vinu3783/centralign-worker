import { Link } from "react-router-dom";
import { CheckCircle2, Clock, Gauge, LifeBuoy, ShieldCheck, XCircle } from "lucide-react";
import { Button, Card, ErrorBanner, PageHeader, StatCard } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { duration, inr } from "../services/format";
import { RunsTable } from "./RunsPage";

export function DashboardPage() {
  const { data: s, error, loading } = useApi(api.stats);
  return (
    <>
      <PageHeader title="Dashboard" subtitle="How the AI worker is performing, and the state of the CRM it operates."
        actions={<Link to="/worker"><Button>Open AI Worker</Button></Link>} />
      <ErrorBanner message={error} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6" data-testid="dashboard-stats">
        <StatCard label="Tasks completed" value={s?.tasks_completed ?? "—"} icon={<CheckCircle2 className="h-4 w-4" />} tone="green" />
        <StatCard label="Tasks failed" value={s?.tasks_failed ?? "—"} icon={<XCircle className="h-4 w-4" />} tone="red" hint="failed or needs attention" />
        <StatCard label="Avg execution" value={duration(s?.avg_execution_ms)} icon={<Clock className="h-4 w-4" />} tone="blue" hint="excl. approval wait" />
        <StatCard label="Success rate" value={s?.success_rate !== null && s?.success_rate !== undefined ? `${Math.round(s.success_rate * 100)}%` : "—"} icon={<Gauge className="h-4 w-4" />} tone="indigo" />
        <StatCard label="Human approvals" value={s?.human_approvals ?? "—"} icon={<ShieldCheck className="h-4 w-4" />} tone="amber" hint={s?.pending_approvals ? `${s.pending_approvals} pending` : undefined} />
        <StatCard label="Failures recovered" value={s?.recovered_failures ?? "—"} icon={<LifeBuoy className="h-4 w-4" />} tone="violet" />
      </div>
      {s && (
        <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-6">
          <StatCard label="Customers" value={s.crm.customers} />
          <StatCard label="High priority" value={s.crm.high_priority} />
          <StatCard label="At risk" value={s.crm.at_risk} />
          <StatCard label="Receivables" value={inr(s.crm.unpaid_amount)} />
          <StatCard label="Overdue invoices" value={s.crm.overdue_invoices} />
          <StatCard label="Open tickets" value={s.crm.open_tickets} />
        </div>
      )}
      <Card title="Recent runs" className="mt-6" bodyClass="p-0">
        <RunsTable rows={s?.recent_runs ?? null} loading={loading} />
      </Card>
    </>
  );
}
