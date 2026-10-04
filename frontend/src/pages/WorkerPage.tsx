import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Bot, FlaskConical, Play, RotateCcw } from "lucide-react";
import { RunView } from "../components/run/RunView";
import { Button, Card, ErrorBanner, cx } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";

const EXAMPLES = [
  "Find unpaid invoices above ₹50,000 and mark their customers as High Priority.",
  "Find all open support tickets with high priority and show me the affected customers.",
  "Find overdue invoices and identify customers who have more than one overdue invoice.",
  "Find customers with open high-priority support tickets and update their status to At Risk.",
];

export function WorkerPage() {
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");
  const [goal, setGoal] = useState(EXAMPLES[0]);
  const [autoApprove, setAutoApprove] = useState(false);
  const [scenario, setScenario] = useState("standard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: scenarios } = useApi(api.scenarios);

  const start = async (fn: () => Promise<{ run_id: string | null }>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      if (res.run_id) setParams({ run: res.run_id });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const resetCrm = async () => {
    if (!window.confirm("Restore the CRM to its original seed data? (Run history is kept.)")) return;
    try {
      await api.resetCrm();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const selected = scenarios?.find((s) => s.id === scenario);
  return (
    <div className="space-y-5">
      <Card className="overflow-hidden" bodyClass="p-0">
        <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 py-5 text-white">
          <div className="flex items-center gap-2 text-sm font-medium text-indigo-100"><Bot className="h-4 w-4" /> CentrAlign Worker</div>
          <h1 className="mt-1 text-2xl font-semibold">What should I accomplish?</h1>
          <p className="mt-1 text-sm text-indigo-100">I'll understand the goal, plan, act on the CRM, observe, recover from failures, ask before risky changes, and verify the outcome.</p>
        </div>
        <div className="space-y-3 p-5">
          <textarea data-testid="goal-input" value={goal} onChange={(e) => setGoal(e.target.value)} rows={3}
            className="w-full resize-y rounded-lg border border-slate-300 px-3 py-2.5 text-[15px] shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20" />
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex, i) => (
              <button key={ex} onClick={() => setGoal(ex)} data-testid={`example-${i + 1}`}
                className={cx("rounded-full border px-2.5 py-1 text-xs transition", goal === ex ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50")}>
                Task {i + 1}: {ex.length > 58 ? `${ex.slice(0, 58)}…` : ex}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
            <Button data-testid="run-task" disabled={busy || goal.trim().length < 3} onClick={() => void start(() => api.createTask(goal, { auto_approve: autoApprove }))}>
              <Play className="h-4 w-4" /> Run Task
            </Button>
            <label className="flex items-center gap-1.5 text-sm text-slate-600">
              <input type="checkbox" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} data-testid="auto-approve" />
              Auto-approve medium-risk changes
            </label>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <select value={scenario} onChange={(e) => setScenario(e.target.value)} data-testid="scenario-select"
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm">
                {scenarios?.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
              </select>
              <Button variant="secondary" data-testid="run-demo" disabled={busy} onClick={() => void start(() => api.runDemo(scenario, autoApprove))}>
                <FlaskConical className="h-4 w-4" /> Run Demo
              </Button>
              <Button variant="ghost" onClick={() => void resetCrm()} title="Restore CRM seed data" data-testid="reset-crm"><RotateCcw className="h-4 w-4" /> Reset CRM</Button>
            </div>
          </div>
          {selected && <p className="text-xs text-slate-500"><b>Demo:</b> {selected.description}</p>}
          <ErrorBanner message={error} />
        </div>
      </Card>

      {runId ? (
        <>
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-500">Run <code className="text-slate-700">{runId}</code></span>
            <Link to={`/runs/${runId}`} className="inline-flex items-center gap-1 text-indigo-600 hover:underline">Run details & audit log <ArrowRight className="h-3.5 w-3.5" /></Link>
          </div>
          <RunView runId={runId} />
        </>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          {[
            ["Real execution", "Every step is an allowlisted tool call against the CRM database — nothing is simulated in the UI."],
            ["Recovery & approval", "Transient failures are retried with backoff; risky writes pause for a human decision."],
            ["Independent verification", "After acting, the worker re-reads ground truth and reports evidence, not claims."],
          ].map(([t, d]) => (
            <div key={t} className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm"><div className="font-semibold text-slate-900">{t}</div><p className="mt-1 text-slate-500">{d}</p></div>
          ))}
        </div>
      )}
    </div>
  );
}
