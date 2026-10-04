import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, X } from "lucide-react";
import { DataTable } from "../components/DataTable";
import { Badge, Button, ErrorBanner, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { dateTime, inr } from "../services/format";
import { CUSTOMER_STATUSES, type Customer, type CustomerStatus } from "../types";

function StatusEditor({ customer, onSaved }: { customer: Customer; onSaved: (c: Customer) => void }) {
  const [value, setValue] = useState<CustomerStatus>(customer.status);
  const [saving, setSaving] = useState(false);
  useEffect(() => setValue(customer.status), [customer.status]);
  const save = async () => {
    setSaving(true);
    try {
      onSaved(await api.updateCustomer(customer.id, { status: value }));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      <select data-testid={`status-select-${customer.id}`} value={value} onChange={(e) => setValue(e.target.value as CustomerStatus)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs">
        {CUSTOMER_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <Button size="sm" variant="secondary" data-testid={`status-save-${customer.id}`} disabled={value === customer.status || saving} onClick={save}>
        {saving ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}

function CustomerDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { data } = useApi(() => api.customer(id), [id]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/20" onClick={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">{data?.company ?? "…"}</h2>
            <p className="text-sm text-slate-500">{data?.name} · {data?.email}</p>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-slate-100"><X className="h-5 w-5" /></button>
        </div>
        {data && (
          <div className="space-y-5 text-sm">
            <div className="flex gap-2"><StatusBadge value={data.status} /><Badge>risk: {data.risk_level}</Badge></div>
            <section>
              <h3 className="mb-2 font-semibold">Invoices</h3>
              {data.invoices.map((i) => (
                <div key={i.id} className="flex justify-between border-b border-slate-100 py-1.5">
                  <span>{i.invoice_number} · due {i.due_date}</span>
                  <span className="flex items-center gap-2 tabular-nums">{inr(i.amount)} <StatusBadge value={i.status} /></span>
                </div>
              ))}
            </section>
            <section>
              <h3 className="mb-2 font-semibold">Support tickets</h3>
              {data.tickets.length === 0 && <p className="text-slate-400">None</p>}
              {data.tickets.map((t) => (
                <div key={t.id} className="flex justify-between gap-2 border-b border-slate-100 py-1.5">
                  <span>#{t.id} {t.subject}</span>
                  <span className="flex gap-1"><StatusBadge value={t.priority} /><StatusBadge value={t.status} /></span>
                </div>
              ))}
            </section>
            <section>
              <h3 className="mb-2 font-semibold">Activity</h3>
              {data.activity.map((a) => (
                <div key={a.id} className="border-b border-slate-100 py-1.5">
                  <div>{a.action}</div>
                  <div className="text-xs text-slate-500">{a.actor} · {dateTime(a.timestamp)}</div>
                </div>
              ))}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

export function CustomersPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [search, setSearch] = useState(q);
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const { data, error, loading, setData } = useApi(() => api.customers({ q, status }), [q, status]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      if (search !== q) setParams(search ? { q: search } : {}, { replace: true });
    }, 250);
    return () => window.clearTimeout(t);
  }, [search, q, setParams]);

  const onSaved = (c: Customer) => {
    setData((rows) => rows?.map((r) => (r.id === c.id ? { ...r, ...c } : r)) ?? null);
    setFlash(`${c.company} → ${c.status}`);
    window.setTimeout(() => setFlash(null), 2500);
  };

  return (
    <>
      <PageHeader title="Customers" subtitle="Accounts in the simulated CRM. Changes here are recorded in the activity log." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input data-testid="customer-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, company, email or #id"
            className={`${inputClass} w-80 pl-8`} />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass} data-testid="customer-status-filter">
          <option value="">All statuses</option>
          {CUSTOMER_STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        {flash && <span data-testid="save-toast" className="rounded-md bg-emerald-50 px-3 py-1.5 text-sm text-emerald-700">Saved: {flash}</span>}
      </div>
      <ErrorBanner message={error} />
      <DataTable<Customer>
        rows={data} loading={loading}
        rowTestId={(c) => `customer-row-${c.id}`}
        onRowClick={(c) => setSelected(c.id)}
        columns={[
          { key: "id", header: "ID", render: (c) => <span className="text-slate-400">#{c.id}</span> },
          { key: "company", header: "Company", render: (c) => <span className="font-medium text-slate-900">{c.company}</span> },
          { key: "name", header: "Contact", render: (c) => <div><div>{c.name}</div><div className="text-xs text-slate-400">{c.email}</div></div> },
          { key: "status", header: "Status", render: (c) => <StatusBadge value={c.status} testId={`status-badge-${c.id}`} /> },
          { key: "risk_level", header: "Risk", render: (c) => <StatusBadge value={c.risk_level} /> },
          { key: "outstanding", header: "Outstanding", align: "right", render: (c) => inr(c.outstanding) },
          { key: "open_tickets", header: "Open tickets", align: "right", render: (c) => c.open_tickets ?? 0 },
          { key: "actions", header: "Change status", render: (c) => <StatusEditor customer={c} onSaved={onSaved} /> },
        ]}
      />
      {selected !== null && <CustomerDrawer id={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
