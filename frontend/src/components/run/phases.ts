import type { RunEvent } from "../../types";

export const PHASES = ["UNDERSTAND", "PLAN", "EXECUTE", "OBSERVE", "ADAPT", "VERIFY", "COMPLETE"] as const;
export type Phase = (typeof PHASES)[number] | "APPROVAL" | "MEMORY" | "START";

export function phaseOf(e: RunEvent): Phase {
  switch (e.type) {
    case "run_started": return "START";
    case "goal": return "UNDERSTAND";
    case "plan": return "PLAN";
    case "memory": return "MEMORY";
    case "tool_call": return e.node === "select_tool" ? "ADAPT" : "EXECUTE";
    case "step": return "EXECUTE";
    case "retry":
    case "recovery": return "ADAPT";
    case "approval":
    case "approval_required":
    case "approval_decision": return "APPROVAL";
    case "verification": return "VERIFY";
    case "summary":
    case "run_completed": return "COMPLETE";
    case "observation": return e.node === "understand_goal" ? "UNDERSTAND" : e.node === "create_plan" ? "PLAN" : "OBSERVE";
    case "node":
      return ({ understand_goal: "UNDERSTAND", create_plan: "PLAN", verify_outcome: "VERIFY" } as Record<string, Phase>)[e.node ?? ""] ?? "EXECUTE";
    default: return "EXECUTE";
  }
}

export const PHASE_STYLE: Record<Phase, string> = {
  START: "bg-slate-100 text-slate-600",
  UNDERSTAND: "bg-sky-100 text-sky-700",
  PLAN: "bg-indigo-100 text-indigo-700",
  EXECUTE: "bg-blue-100 text-blue-700",
  OBSERVE: "bg-teal-100 text-teal-700",
  ADAPT: "bg-amber-100 text-amber-800",
  APPROVAL: "bg-orange-100 text-orange-800",
  VERIFY: "bg-violet-100 text-violet-700",
  COMPLETE: "bg-emerald-100 text-emerald-700",
  MEMORY: "bg-fuchsia-100 text-fuchsia-700",
};
