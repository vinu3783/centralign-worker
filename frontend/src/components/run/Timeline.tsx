import { useEffect, useMemo, useRef } from "react";
import type { RunEvent } from "../../types";
import { duration, time } from "../../services/format";
import { Badge, Collapsible, JsonView, StatusIcon, cx } from "../ui";
import { PHASE_STYLE, phaseOf } from "./phases";

interface Entry { key: string; event: RunEvent; start?: RunEvent }

/** Merge tool_call running/finished pairs into one entry. */
function toEntries(events: RunEvent[]): Entry[] {
  const out: Entry[] = [];
  const open = new Map<string, number>();
  for (const e of events) {
    // Step start/finish events collapse into one entry that shows the step's final status.
    const mergeKey = e.type === "tool_call" && e.call_id ? e.call_id : e.type === "step" && e.step_id ? `step:${e.step_id}` : null;
    if (mergeKey) {
      const idx = open.get(mergeKey);
      if (idx !== undefined) {
        out[idx] = { key: out[idx].key, event: e, start: out[idx].event };
        continue;
      }
      open.set(mergeKey, out.length);
    }
    out.push({ key: `e${e.seq}`, event: e });
  }
  return out;
}

export function Timeline({ events, autoScroll = true }: { events: RunEvent[]; autoScroll?: boolean }) {
  const entries = useMemo(() => toEntries(events), [events]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (autoScroll) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [entries.length, autoScroll]);

  if (!events.length) return <p className="py-8 text-center text-sm text-slate-400">Waiting for the agent…</p>;
  return (
    <ol className="relative space-y-1" data-testid="timeline">
      {entries.map(({ key, event: e }, i) => (
        // Only the newest entry can still be in progress; older "running" markers are just milestones.
        <TimelineItem key={key} e={e.status === "running" && i < entries.length - 1 ? { ...e, status: "info" } : e} />
      ))}
      <div ref={end} />
    </ol>
  );
}

function TimelineItem({ e }: { e: RunEvent }) {
  const phase = phaseOf(e);
  const isCall = e.type === "tool_call";
  const tone = e.status === "error" ? "border-rose-200 bg-rose-50/50" : e.status === "warning" ? "border-amber-200 bg-amber-50/40"
    : e.status === "waiting" ? "border-orange-300 bg-orange-50" : "border-transparent";
  return (
    <li className={cx("slide-in rounded-lg border px-3 py-2", tone)} data-testid="timeline-item" data-type={e.type} data-status={e.status}>
      <div className="flex items-start gap-2.5">
        <StatusIcon status={e.status} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={cx("rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide", PHASE_STYLE[phase])}>{phase}</span>
            <span className={cx("text-sm text-slate-800", isCall && "font-mono text-[12.5px]")}>{e.title}</span>
            {isCall && (e.attempt ?? 1) > 1 && <Badge tone="amber">attempt {e.attempt}</Badge>}
            {e.injected_fault && <Badge tone="red">injected fault: {e.injected_fault}</Badge>}
            {isCall && e.error_code && <Badge tone={e.retryable ? "amber" : "red"}>{e.error_code}{e.retryable ? " · retryable" : ""}</Badge>}
          </div>
          {e.error && <div className="mt-0.5 text-xs text-rose-700">{e.error}</div>}
          {e.detail && <div className="mt-0.5 text-xs text-slate-500">{e.detail}</div>}
          {e.message && <div className="mt-1 text-xs text-slate-700">{e.message}</div>}
          {e.notes && e.notes.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-xs text-amber-800">{e.notes.map((n, i) => <li key={i}>↳ {n}</li>)}</ul>
          )}
          {(e.expected || e.actual) && e.type === "observation" && (
            <div className="mt-0.5 text-xs text-slate-500">expected <b>{e.expected}</b> · observed <b>{e.actual}</b></div>
          )}
          <Details e={e} />
        </div>
        <div className="shrink-0 text-right text-[11px] tabular-nums text-slate-400">
          <div>{time(e.timestamp)}</div>
          {e.duration_ms !== undefined && <div>{duration(e.duration_ms)}</div>}
        </div>
      </div>
    </li>
  );
}

function Details({ e }: { e: RunEvent }) {
  if (e.type === "tool_call" && e.status !== "running") {
    const count = Array.isArray(e.output) ? `${e.output.length} records` : e.output ? "result" : "error";
    return <div className="mt-1"><Collapsible summary={`Tool input / output (${count})`}><div className="grid gap-2 lg:grid-cols-2"><JsonView value={e.input} /><JsonView value={e.output ?? { error: e.error, code: e.error_code }} /></div></Collapsible></div>;
  }
  if (e.type === "goal" && e.goal) return <div className="mt-1"><Collapsible summary="Structured goal (JSON)"><JsonView value={e.goal} /></Collapsible></div>;
  if (e.type === "plan" && e.steps) {
    return (
      <div className="mt-1">
        {Array.isArray(e.errors) && <ul className="mb-1 text-xs text-rose-700">{(e.errors as string[]).map((x, i) => <li key={i}>✗ {x}</li>)}</ul>}
        <Collapsible summary="Plan steps"><JsonView value={e.steps} /></Collapsible>
      </div>
    );
  }
  if (e.type === "verification" && e.checks) {
    return (
      <ul className="mt-1 space-y-0.5 text-xs">
        {e.checks.map((c, i) => <li key={i} className={c.passed ? "text-emerald-700" : "text-rose-700"}>{c.passed ? "✓" : "✗"} {c.name} — expected {String(Array.isArray(c.expected) ? c.expected.length : c.expected)}, observed {String(Array.isArray(c.observed) ? c.observed.length : c.observed)}</li>)}
      </ul>
    );
  }
  if (e.type === "summary" && e.lines) return <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">{e.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>;
  return null;
}
