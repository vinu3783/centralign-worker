import { useState } from "react";
import { Link } from "react-router-dom";
import { Bot, User } from "lucide-react";
import { AuditTable } from "../components/AuditTable";
import { Card, ErrorBanner, PageHeader, cx } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { dateTime } from "../services/format";

export function ActivityPage() {
  const [tab, setTab] = useState<"crm" | "audit">("crm");
  const crm = useApi(() => api.activity({ limit: 150 }), []);
  const audit = useApi(() => api.audit({ limit: 300 }), []);

  return (
    <>
      <PageHeader title="Activity" subtitle="Business history in the CRM, and the agent's complete audit log." />
      <div className="mb-4 inline-flex rounded-lg border border-slate-200 bg-white p-1 text-sm">
        {(["crm", "audit"] as const).map((t) => (
          <button key={t} data-testid={`tab-${t}`} onClick={() => setTab(t)}
            className={cx("rounded-md px-3 py-1.5 font-medium", tab === t ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-50")}>
            {t === "crm" ? "CRM activity" : "Agent audit log"}
          </button>
        ))}
      </div>
      {tab === "crm" ? (
        <Card bodyClass="p-0">
          <ErrorBanner message={crm.error} />
          <ul className="divide-y divide-slate-100" data-testid="activity-list">
            {crm.data?.map((a) => {
              const agent = a.actor.startsWith("CentrAlign");
              const runId = typeof a.metadata?.run_id === "string" ? a.metadata.run_id : null;
              return (
                <li key={a.id} className="flex items-start gap-3 px-4 py-3">
                  <span className={cx("mt-0.5 rounded-full p-1.5", agent ? "bg-indigo-50 text-indigo-600" : "bg-slate-100 text-slate-500")}>
                    {agent ? <Bot className="h-4 w-4" /> : <User className="h-4 w-4" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-slate-900"><span className="font-medium">{a.customer_name ?? "—"}</span> · {a.action}</div>
                    <div className="text-xs text-slate-500">
                      {a.actor} · {dateTime(a.timestamp)}
                      {runId && <> · <Link className="text-indigo-600 hover:underline" to={`/runs/${runId}`}>{runId}</Link></>}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : (
        <AuditTable rows={audit.data} loading={audit.loading} showRun />
      )}
    </>
  );
}
