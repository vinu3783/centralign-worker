import { useEffect, useState, type ReactNode } from "react";
import { ShieldAlert } from "lucide-react";
import { api } from "../../services/api";
import { display, duration, inr } from "../../services/format";
import type { Approval, LiveState, Plan, RunDetail, StructuredGoal } from "../../types";
import { Badge, Button, Card, StatusBadge, StatusIcon, cx, inputClass } from "../ui";

const OPS: Record<string, string> = { equals: "=", not_equals: "≠", greater_than: ">", greater_or_equal: "≥", less_than: "<", less_or_equal: "≤", in: "in" };

export function GoalCard({ goal }: { goal: StructuredGoal }) {
  return (
    <Card title="Goal understanding" testId="goal-card">
      <p className="text-sm text-slate-800">{goal.objective}</p>
      <div className="mt-3 space-y-2 text-xs">
        <Row label="Entities">{goal.entities.map((e) => <Badge key={e} tone="blue">{e}</Badge>)}</Row>
        <Row label="Conditions">
          {goal.conditions.length ? goal.conditions.map((c, i) => (
            <Badge key={i} tone="slate"><span className="font-mono">{c.entity}.{c.field} {OPS[c.operator] ?? c.operator} {c.field === "amount" ? inr(Number(c.value)) : display(c.value)}</span></Badge>
          )) : <span className="text-slate-400">none</span>}
          {goal.group_condition && <Badge tone="violet">group by {goal.group_condition.by} · count ≥ {goal.group_condition.min_count}</Badge>}
        </Row>
        <Row label="Actions">
          {goal.actions.length ? goal.actions.map((a, i) => <Badge key={i} tone="indigo">{a.type}{a.value ? ` → ${a.value}` : ""}{a.channel === "browser" ? " (browser)" : ""}</Badge>) : <span className="text-slate-400">read-only</span>}
        </Row>
        <Row label="Required">{goal.required_actions.map((a) => <span key={a} className="font-mono text-slate-500">{a}</span>)}</Row>
        {goal.clarification_needed && <p className="rounded bg-amber-50 p-2 text-amber-800">{goal.clarification_needed}</p>}
      </div>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-1.5"><span className="w-20 shrink-0 text-slate-500">{label}</span>{children}</div>;
}

const RISK_TONE = { low: "slate", medium: "amber", high: "red" } as const;

export function PlanCard({ plan, live }: { plan: Plan; live: LiveState | null }) {
  return (
    <Card title={<span>Plan <span className="font-normal text-slate-400">· {plan.steps.length} steps · {plan.source === "llm" ? "LLM planner" : "rule-based planner"}</span></span>} testId="plan-card">
      {plan.rationale && <p className="mb-3 text-xs text-slate-500">{plan.rationale}</p>}
      <ol className="space-y-2">
        {plan.steps.map((s, i) => {
          const sr = live?.step_runs[s.id];
          const st = sr?.status;
          const icon = st === "completed" ? "success" : st === "running" ? "running" : st === "failed" ? "error"
            : st === "partial" || st === "rejected" ? "warning" : st === "skipped" ? "info" : undefined;
          const counts = sr?.item_status?.length ? sr.item_status : null;
          return (
            <li key={s.id} className={cx("flex gap-2.5 rounded-lg border px-3 py-2", live?.current_step === s.id && st === "running" ? "border-indigo-300 bg-indigo-50/50" : "border-slate-100")} data-testid={`plan-step-${s.id}`}>
              <StatusIcon status={icon} className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="text-sm text-slate-800"><span className="text-slate-400">{i + 1}.</span> {s.description}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700">{s.tool}</code>
                  {s.risk && <Badge tone={RISK_TONE[s.risk as keyof typeof RISK_TONE] ?? "slate"}>{s.risk} risk</Badge>}
                  {s.for_each && <span className="font-mono text-slate-400">for each {s.for_each}</span>}
                  {s.remediation_of && <Badge tone="amber">remediation</Badge>}
                  {counts && <span className="text-slate-500">{counts.filter((c) => c === "succeeded").length}/{counts.length} done{counts.includes("compliant") ? ` · ${counts.filter((c) => c === "compliant").length} already ok` : ""}{counts.includes("failed") ? ` · ${counts.filter((c) => c === "failed").length} failed` : ""}</span>}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

export function ApprovalCard({ runId, approval, onDecided }: { runId: string; approval: Approval; onDecided: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const decide = async (kind: "approve" | "reject") => {
    setBusy(kind);
    setError(null);
    try {
      await (kind === "approve" ? api.approve : api.reject)(runId, "operator", comment || undefined);
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="rounded-xl border-2 border-orange-300 bg-orange-50 p-4 shadow-sm" data-testid="approval-card">
      <div className="flex items-center gap-2 text-sm font-semibold text-orange-900"><ShieldAlert className="h-5 w-5" /> Approval required · {approval.risk_level.toUpperCase()} risk</div>
      <p className="mt-2 text-sm text-slate-800" data-testid="approval-message">{approval.message}</p>
      <div className="mt-3 overflow-hidden rounded-lg border border-orange-200 bg-white">
        <table className="w-full text-xs">
          <thead className="bg-orange-100/60 text-left text-orange-900"><tr><th className="px-3 py-1.5">Record</th><th className="px-3 py-1.5">Current</th><th className="px-3 py-1.5">Proposed</th></tr></thead>
          <tbody>
            {approval.preview.map((p, i) => (
              <tr key={i} className="border-t border-orange-100">
                <td className="px-3 py-1.5 font-medium">{display(p.label)} {p.entity_id ? <span className="text-slate-400">#{display(p.entity_id)}</span> : null}</td>
                <td className="px-3 py-1.5">{p.exists === false ? <span className="text-rose-600">not found</span> : display(p.current)}</td>
                <td className="px-3 py-1.5 font-medium text-indigo-700">{display(p.desired ?? p.call)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Optional comment" className={`${inputClass} mt-3 w-full`} />
      {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
      <div className="mt-3 flex gap-2">
        <Button variant="success" data-testid="approve-button" disabled={!!busy} onClick={() => void decide("approve")}>{busy === "approve" ? "Approving…" : "Approve"}</Button>
        <Button variant="danger" data-testid="reject-button" disabled={!!busy} onClick={() => void decide("reject")}>{busy === "reject" ? "Rejecting…" : "Reject"}</Button>
      </div>
    </section>
  );
}

export function StatusCard({ run, connection }: { run: RunDetail; connection: string }) {
  const [now, setNow] = useState(Date.now());
  const active = ["running", "verifying", "awaiting_approval"].includes(run.status);
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(t);
  }, [active]);
  const elapsed = active ? now - new Date(run.started_at).getTime() : run.metrics.duration_ms;
  const live = run.live;
  return (
    <Card title="Run status" actions={<StatusBadge value={run.status} testId="run-status" />} testId="status-card">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
        <Item label="Current step">{live?.current_step ?? "—"}</Item>
        <Item label="Tool"><code className="text-xs">{live?.current_tool ?? "—"}</code></Item>
        <Item label="Elapsed">{duration(elapsed)}</Item>
        <Item label="Tool calls">{live?.tool_calls ?? run.metrics.tool_calls ?? 0}</Item>
        <Item label="Retries"><span data-testid="retry-count">{live?.retry_count ?? run.metrics.retries ?? 0}</span></Item>
        <Item label="Approval">{live?.approval_status ?? "none"}</Item>
        <Item label="Engine"><span className="text-xs">{run.mode === "demo" ? "DEMO (rules)" : run.model}</span></Item>
        <Item label="Stream"><span className={cx("text-xs", connection === "live" ? "text-emerald-600" : "text-slate-500")}>{connection}</span></Item>
      </dl>
    </Card>
  );
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="font-medium text-slate-800">{children}</dd></div>;
}
