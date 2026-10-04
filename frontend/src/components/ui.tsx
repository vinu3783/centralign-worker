import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Circle, Clock, Loader2, XCircle } from "lucide-react";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

type Tone = "slate" | "indigo" | "green" | "amber" | "red" | "blue" | "violet";
const TONES: Record<Tone, string> = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function Badge({ tone = "slate", children, className, testId }: { tone?: Tone; children: ReactNode; className?: string; testId?: string }) {
  return (
    <span data-testid={testId} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  // run statuses
  running: "blue", verifying: "violet", awaiting_approval: "amber", completed: "green", needs_attention: "red",
  rejected: "slate", failed: "red", needs_clarification: "amber",
  // CRM
  Active: "green", "High Priority": "violet", "At Risk": "red", Inactive: "slate",
  paid: "green", unpaid: "blue", overdue: "red", open: "blue", in_progress: "amber", resolved: "green", closed: "slate",
  high: "red", medium: "amber", low: "slate",
  // misc
  success: "green", error: "red", approved: "green", pending: "amber", auto_approved: "indigo", waiting: "amber",
};

export function StatusBadge({ value, testId }: { value: string | null | undefined; testId?: string }) {
  if (!value) return <span className="text-slate-400">—</span>;
  return <Badge tone={STATUS_TONE[value] ?? "slate"} testId={testId}>{value.replace(/_/g, " ")}</Badge>;
}

export function Card({ title, actions, children, className, bodyClass, testId }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; testId?: string;
}) {
  return (
    <section data-testid={testId} className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {actions}
        </header>
      )}
      <div className={cx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function StatCard({ label, value, hint, icon, tone = "slate" }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</span>
        {icon && <span className={cx("rounded-lg p-1.5 ring-1 ring-inset", TONES[tone])}>{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Button({ children, variant = "primary", size = "md", className, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "success" | "ghost"; size?: "sm" | "md" }) {
  const variants = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm",
    secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50",
    danger: "bg-rose-600 text-white hover:bg-rose-700 shadow-sm",
    success: "bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm",
    ghost: "text-slate-600 hover:bg-slate-100",
  };
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm" };
  return (
    <button {...props} className={cx("inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50", variants[variant], sizes[size], className)}>
      {children}
    </button>
  );
}

export const inputClass = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-4 w-4 animate-spin", className)} />;
}

export function StatusIcon({ status, className }: { status?: string; className?: string }) {
  const c = cx("h-4 w-4 shrink-0", className);
  switch (status) {
    case "running": return <Loader2 className={cx(c, "animate-spin text-sky-600")} />;
    case "success": return <CheckCircle2 className={cx(c, "text-emerald-600")} />;
    case "error": return <XCircle className={cx(c, "text-rose-600")} />;
    case "warning": return <AlertTriangle className={cx(c, "text-amber-500")} />;
    case "waiting": return <Clock className={cx(c, "text-amber-500")} />;
    default: return <Circle className={cx(c, "text-slate-400")} />;
  }
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{message}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function JsonView({ value, maxHeight = "max-h-72" }: { value: unknown; maxHeight?: string }) {
  return (
    <pre className={cx("overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100", maxHeight)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Collapsible({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-1 text-left text-xs font-medium text-slate-500 hover:text-slate-800">
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {summary}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}
