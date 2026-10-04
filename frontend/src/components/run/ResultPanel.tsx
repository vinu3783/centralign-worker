import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import { display, inr, titleCase } from "../../services/format";
import type { EvidenceItem, FinalResult, ResultTable } from "../../types";
import { Badge, Card, Collapsible, JsonView, cx } from "../ui";

const HEADLINE_TONE: Record<string, string> = {
  completed: "border-emerald-200 bg-emerald-50 text-emerald-900",
  needs_attention: "border-rose-200 bg-rose-50 text-rose-900",
  failed: "border-rose-200 bg-rose-50 text-rose-900",
  rejected: "border-slate-200 bg-slate-50 text-slate-800",
  needs_clarification: "border-amber-200 bg-amber-50 text-amber-900",
};

export function ResultPanel({ result }: { result: FinalResult }) {
  const changes = result.changes.filter((c) => c.kind === "change" || c.kind === "message" || c.kind === "artifact");
  return (
    <div className="space-y-4" data-testid="result-panel">
      <div className={cx("rounded-xl border p-4", HEADLINE_TONE[result.status])}>
        <div className="flex items-center gap-2 text-base font-semibold" data-testid="result-headline">
          {result.status === "completed" ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <XCircle className="h-5 w-5" />}
          {result.headline}
        </div>
        <ul className="mt-2 space-y-0.5 text-sm" data-testid="result-lines">
          {result.summary_lines.map((l, i) => <li key={i}>• {l}</li>)}
        </ul>
      </div>

      {result.verification && (
        <Card title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-violet-600" /> Independent verification</span>}
          actions={<Badge tone={result.verification.passed ? "green" : "red"}>{result.verification.passed ? "PASS" : "FAIL"} · attempt {result.verification.attempt}</Badge>} testId="verification-card">
          <ul className="space-y-2">
            {result.verification.checks.map((c, i) => (
              <li key={i} className="text-sm">
                <div className="flex items-start gap-2">
                  {c.passed ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />}
                  <div className="min-w-0 flex-1">
                    <div>{c.name} <Badge className="ml-1">{c.kind.replace(/_/g, " ")}</Badge></div>
                    <div className="text-xs text-slate-500">expected {fmt(c.expected)} · observed {fmt(c.observed)}</div>
                    {c.details.length > 0 && <Collapsible summary="Verification query results"><JsonView value={c.details} /></Collapsible>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {changes.length > 0 && (
        <Card title="Evidence of changes" testId="evidence-card" bodyClass="p-0">
          <EvidenceTable items={changes} />
        </Card>
      )}

      {result.results.map((t, i) => <ResultTableCard key={i} table={t} />)}
    </div>
  );
}

function fmt(v: unknown) {
  return Array.isArray(v) ? `[${v.length}]` : display(v);
}

export function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr><th className="px-4 py-2">Record</th><th className="px-4 py-2">Change</th><th className="px-4 py-2">Verified</th><th className="px-4 py-2">Proof</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((e, i) => (
            <tr key={i} data-testid="evidence-row">
              <td className="px-4 py-2"><div className="font-medium text-slate-900">{e.label}</div><div className="text-xs text-slate-400">{e.entity} {e.entity_id ? `#${e.entity_id}` : ""}</div></td>
              <td className="px-4 py-2">
                {e.field ? <span>{e.field}: <span className="text-slate-500">{display(e.before)}</span> → <b>{display(e.after)}</b>{e.details.changed === false && <Badge className="ml-1">no-op</Badge>}</span>
                  : <span className="text-slate-600">{e.kind === "artifact" ? `report ${display(e.details.file)} (${display(e.details.rows)} rows)` : `message to ${display(e.details.to)}`}</span>}
              </td>
              <td className="px-4 py-2">
                {e.verified === true ? <Badge tone="green">✓ verified</Badge> : e.verified === false ? <Badge tone="red">✗ not persisted</Badge> : <Badge>n/a</Badge>}
              </td>
              <td className="px-4 py-2 text-xs text-slate-500">
                {display(e.details.tool)} · call {display(e.call_id ?? e.details.call_id)} · {display(e.details.attempts)} attempt(s)
                {typeof e.details.screenshot === "string" && <> · <a className="text-indigo-600 underline" href={e.details.screenshot} target="_blank" rel="noreferrer">screenshot</a></>}
                {typeof e.details.url === "string" && <> · <a className="text-indigo-600 underline" href={e.details.url} target="_blank" rel="noreferrer">download</a></>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultTableCard({ table }: { table: ResultTable }) {
  return (
    <Card title={<span>{table.title} <span className="font-normal text-slate-400">· {table.rows.length} rows</span></span>} bodyClass="p-0">
      <div className="max-h-80 overflow-auto">
        <table className="min-w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>{table.columns.map((c) => <th key={c} className="px-4 py-2">{c === "key" ? "Customer ID" : c === "label" ? "Customer" : titleCase(c)}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {table.rows.length === 0 && <tr><td colSpan={table.columns.length} className="px-4 py-6 text-center text-slate-400">No matching records</td></tr>}
            {table.rows.map((r, i) => (
              <tr key={i}>
                {table.columns.map((c) => (
                  <td key={c} className="px-4 py-1.5">
                    {c === "amount" || c === "total" ? inr(Number(r[c])) : c === "status" && "status_before" in r && r.status !== r.status_before
                      ? <b className="text-indigo-700">{display(r[c])}</b> : display(r[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
