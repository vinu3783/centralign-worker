import { useCallback, useEffect, useRef, useState } from "react";
import { Card, Spinner } from "../ui";
import { useRunStream } from "../../hooks/useRunStream";
import { api } from "../../services/api";
import type { RunDetail, RunEvent } from "../../types";
import { PhaseStepper } from "./PhaseStepper";
import { ResultPanel } from "./ResultPanel";
import { ApprovalCard, GoalCard, PlanCard, StatusCard } from "./RunCards";
import { Timeline } from "./Timeline";

/** Live run detail: re-fetched whenever new events stream in (debounced). */
export function useLiveRun(runId: string) {
  const { events, connection } = useRunStream(runId);
  const [run, setRun] = useState<RunDetail | null>(null);
  const timer = useRef<number>(undefined);

  const refresh = useCallback(async () => {
    try {
      setRun(await api.run(runId));
    } catch { /* transient; next event triggers another refresh */ }
  }, [runId]);

  useEffect(() => {
    setRun(null);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!events.length) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void refresh(), 150);
  }, [events.length, refresh]);

  return { run, events, connection, refresh };
}

export function RunView({ runId, onFinished }: { runId: string; onFinished?: (run: RunDetail) => void }) {
  const { run, events, connection, refresh } = useLiveRun(runId);
  const finished = events.some((e: RunEvent) => e.type === "run_completed");
  const notified = useRef(false);
  useEffect(() => {
    notified.current = false;
  }, [runId]);
  useEffect(() => {
    if (finished && run?.final_result && !notified.current) {
      notified.current = true;
      onFinished?.(run);
    }
  }, [finished, run, onFinished]);

  const pending = run?.approvals.find((a) => a.status === "pending");
  return (
    <div className="space-y-4">
      <PhaseStepper events={events} finished={finished} />
      <div className="grid gap-4 xl:grid-cols-12">
        <Card title="Live execution timeline" className="xl:col-span-7" bodyClass="max-h-[70vh] overflow-y-auto p-3"
          actions={<span className="text-xs text-slate-400">{events.length} events</span>} testId="timeline-card">
          <Timeline events={events} />
        </Card>
        <div className="space-y-4 xl:col-span-5">
          {pending && run && <ApprovalCard runId={run.id} approval={pending} onDecided={() => void refresh()} />}
          {run ? <StatusCard run={run} connection={connection} /> : <Spinner />}
          {run?.structured_goal && <GoalCard goal={run.structured_goal} />}
          {run?.plan && <PlanCard plan={run.plan} live={run.live} />}
        </div>
      </div>
      {run?.final_result && <ResultPanel result={run.final_result} />}
      {run?.error && !run.final_result && <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{run.error}</div>}
    </div>
  );
}
