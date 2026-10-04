import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { duration, time } from "../services/format";
import type { AuditEntry } from "../types";
import { JsonView, Spinner, StatusBadge } from "./ui";

export function AuditTable({ rows, loading, showRun = false }: { rows: AuditEntry[] | null; loading?: boolean; showRun?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!rows) return loading ? <Spinner /> : null;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm" data-testid="audit-table">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="w-6" />
            <th className="px-3 py-2">Time</th>
            {showRun && <th className="px-3 py-2">Run</th>}
            <th className="px-3 py-2">Agent step</th>
            <th className="px-3 py-2">Tool</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Error</th>
            <th className="px-3 py-2 text-right">Duration</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((a) => (
            <Fragment key={a.id}>
              <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <td className="pl-3 text-slate-400">{open === a.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</td>
                <td className="px-3 py-2 tabular-nums text-slate-500">{time(a.timestamp)}</td>
                {showRun && <td className="px-3 py-2"><Link onClick={(e) => e.stopPropagation()} className="font-mono text-xs text-indigo-600 hover:underline" to={`/runs/${a.run_id}`}>{a.run_id}</Link></td>}
                <td className="px-3 py-2 font-mono text-xs">{a.agent_step}</td>
                <td className="px-3 py-2 font-mono text-xs">{a.tool ?? "—"}</td>
                <td className="px-3 py-2"><StatusBadge value={a.status} /></td>
                <td className="max-w-xs truncate px-3 py-2 text-xs text-rose-700">{a.error}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{a.duration_ms !== null ? duration(a.duration_ms) : ""}</td>
              </tr>
              {open === a.id && (
                <tr><td colSpan={showRun ? 8 : 7} className="bg-slate-50 px-4 py-3"><div className="grid gap-3 lg:grid-cols-2"><div><div className="mb-1 text-xs font-medium text-slate-500">Input</div><JsonView value={a.input} /></div><div><div className="mb-1 text-xs font-medium text-slate-500">Output</div><JsonView value={a.output} /></div></div></td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
