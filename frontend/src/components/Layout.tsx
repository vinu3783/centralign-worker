import { NavLink, Outlet } from "react-router-dom";
import { Activity, Bot, History, LayoutDashboard, Receipt, Ticket, Users } from "lucide-react";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { Badge, cx } from "./ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/worker", label: "AI Worker", icon: Bot },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/invoices", label: "Invoices", icon: Receipt },
  { to: "/tickets", label: "Tickets", icon: Ticket },
  { to: "/runs", label: "Runs", icon: History },
  { to: "/activity", label: "Activity", icon: Activity },
];

export function Layout() {
  const { data: system } = useApi(api.system);
  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-indigo-600 text-white shadow-sm"><Bot className="h-5 w-5" /></div>
          <div>
            <div className="text-sm font-semibold leading-tight text-slate-900">CentrAlign Worker</div>
            <div className="text-xs text-slate-500">Autonomous AI task worker</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} data-testid={`nav-${label.toLowerCase().replace(/ /g, "-")}`}
              className={({ isActive }) => cx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="m-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs" data-testid="mode-indicator">
          <div className="mb-1 font-medium text-slate-700">Reasoning engine</div>
          {system ? (
            <>
              <Badge tone={system.mode === "demo" ? "amber" : "green"}>{system.mode === "demo" ? "DEMO MODE" : "LLM MODE"}</Badge>
              <div className="mt-1.5 break-words text-slate-500">{system.model}</div>
              <div className="mt-1 text-slate-400">Approval ≥ {system.approval_threshold} risk · {system.tools} tools</div>
            </>
          ) : <span className="text-slate-400">connecting…</span>}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <nav className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-3 py-2 md:hidden">
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} className={({ isActive }) => cx("whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium", isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600")}>{label}</NavLink>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8"><Outlet /></main>
      </div>
    </div>
  );
}
