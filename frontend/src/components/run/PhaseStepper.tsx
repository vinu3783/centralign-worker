import { Check } from "lucide-react";
import type { RunEvent } from "../../types";
import { cx } from "../ui";
import { PHASES, phaseOf } from "./phases";

/** GOAL → UNDERSTAND → PLAN → EXECUTE → OBSERVE → ADAPT → VERIFY → COMPLETE, lit up from live events. */
export function PhaseStepper({ events, finished }: { events: RunEvent[]; finished: boolean }) {
  const seen = new Set(events.map(phaseOf));
  const last = events.length ? phaseOf(events[events.length - 1]) : null;
  const waiting = events.some((e) => e.type === "approval_required") &&
    !events.some((e) => e.type === "approval_decision" && e.seq > Math.max(...events.filter((x) => x.type === "approval_required").map((x) => x.seq)));
  const failed = events.some((e) => e.type === "run_completed" && e.final_status !== "completed");

  return (
    <div className="flex items-center overflow-x-auto rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm" data-testid="phase-stepper">
      <Pill label="GOAL" state={events.length ? "done" : "active"} />
      {PHASES.map((p) => {
        const active = !finished && (last === p || (p === "EXECUTE" && last === "APPROVAL"));
        const state = p === "COMPLETE" && finished ? (failed ? "warn" : "done")
          : active ? "active" : seen.has(p) ? (p === "ADAPT" ? "adapt" : "done") : "todo";
        return (
          <div key={p} className="flex items-center">
            <div className={cx("mx-1 h-px w-4 sm:w-6", seen.has(p) ? "bg-indigo-300" : "bg-slate-200")} />
            <Pill label={p} state={state} sub={p === "EXECUTE" && waiting ? "awaiting approval" : p === "ADAPT" && !seen.has(p) && finished ? "not needed" : undefined} />
          </div>
        );
      })}
    </div>
  );
}

function Pill({ label, state, sub }: { label: string; state: "todo" | "active" | "done" | "adapt" | "warn"; sub?: string }) {
  return (
    <div className="flex flex-col items-center" data-testid={`phase-${label}`} data-state={state}>
      <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide",
        state === "todo" && "bg-slate-100 text-slate-400",
        state === "active" && "bg-indigo-600 text-white pulse-ring",
        state === "done" && "bg-indigo-50 text-indigo-700",
        state === "adapt" && "bg-amber-100 text-amber-800",
        state === "warn" && "bg-rose-100 text-rose-700")}>
        {(state === "done" || state === "adapt") && <Check className="h-3 w-3" />}
        {label}
      </span>
      {sub && <span className="mt-0.5 text-[10px] text-slate-400">{sub}</span>}
    </div>
  );
}
