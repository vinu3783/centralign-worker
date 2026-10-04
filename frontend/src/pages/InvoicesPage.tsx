import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DataTable } from "../components/DataTable";
import { ErrorBanner, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { inr } from "../services/format";
import type { Invoice } from "../types";

export function InvoicesPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [q, setQ] = useState(params.get("q") ?? "");
  const { data, error, loading } = useApi(
    () => api.invoices({ status, min_amount: minAmount ? Number(minAmount) : undefined, q }),
    [status, minAmount, q],
  );
  const total = data?.reduce((s, i) => s + i.amount, 0) ?? 0;

  return (
    <>
      <PageHeader title="Invoices" subtitle="'Unpaid' = not yet due · 'Overdue' = unpaid and past its due date." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search invoice # or customer" className={`${inputClass} w-64`} data-testid="invoice-search" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass} data-testid="invoice-status-filter">
          <option value="">All statuses</option>
          <option value="unpaid">Unpaid</option>
          <option value="overdue">Overdue</option>
          <option value="paid">Paid</option>
        </select>
        <input type="number" min={0} step={1000} value={minAmount} onChange={(e) => setMinAmount(e.target.value)} placeholder="Amount above (₹)"
          className={`${inputClass} w-44`} data-testid="invoice-min-amount" />
        <span className="ml-auto text-sm text-slate-500" data-testid="invoice-count">{data?.length ?? 0} invoices · {inr(total)}</span>
      </div>
      <ErrorBanner message={error} />
      <DataTable<Invoice>
        rows={data} loading={loading} rowTestId={(i) => `invoice-row-${i.id}`}
        columns={[
          { key: "invoice_number", header: "Invoice", render: (i) => <span className="font-mono text-xs">{i.invoice_number}</span> },
          { key: "customer_name", header: "Customer", render: (i) => <span className="font-medium text-slate-900">{i.customer_name}</span> },
          { key: "amount", header: "Amount", align: "right", render: (i) => inr(i.amount) },
          { key: "due_date", header: "Due date", render: (i) => <span>{i.due_date}{i.days_overdue > 0 && <span className="ml-1.5 text-xs text-rose-600">{i.days_overdue}d late</span>}</span> },
          { key: "status", header: "Status", render: (i) => <StatusBadge value={i.status} /> },
        ]}
      />
    </>
  );
}
