import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DataTable } from "../components/DataTable";
import { ErrorBanner, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { Ticket } from "../types";

export function TicketsPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [q, setQ] = useState(params.get("q") ?? "");
  const { data, error, loading, setData } = useApi(() => api.tickets({ status, priority, q }), [status, priority, q]);

  const changePriority = async (t: Ticket, p: Ticket["priority"]) => {
    const updated = await api.updateTicket(t.id, { priority: p });
    setData((rows) => rows?.map((r) => (r.id === t.id ? updated : r)) ?? null);
  };

  return (
    <>
      <PageHeader title="Support tickets" />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search subject or customer" className={`${inputClass} w-64`} />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass} data-testid="ticket-status-filter">
          <option value="">All statuses</option>
          {["open", "in_progress", "resolved", "closed"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </select>
        <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inputClass} data-testid="ticket-priority-filter">
          <option value="">All priorities</option>
          {["high", "medium", "low"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <ErrorBanner message={error} />
      <DataTable<Ticket>
        rows={data} loading={loading} rowTestId={(t) => `ticket-row-${t.id}`}
        columns={[
          { key: "id", header: "ID", render: (t) => <span className="text-slate-400">#{t.id}</span> },
          { key: "subject", header: "Subject", render: (t) => <span className="font-medium text-slate-900">{t.subject}</span> },
          { key: "customer_name", header: "Customer" },
          { key: "status", header: "Status", render: (t) => <StatusBadge value={t.status} /> },
          {
            key: "priority", header: "Priority", render: (t) => (
              <div className="flex items-center gap-2">
                <StatusBadge value={t.priority} />
                <select aria-label="Change priority" data-testid={`priority-select-${t.id}`} value={t.priority}
                  onChange={(e) => void changePriority(t, e.target.value as Ticket["priority"])}
                  className="rounded-md border border-slate-300 bg-white px-1.5 py-0.5 text-xs">
                  {["low", "medium", "high"].map((p) => <option key={p}>{p}</option>)}
                </select>
              </div>
            ),
          },
        ]}
      />
    </>
  );
}
