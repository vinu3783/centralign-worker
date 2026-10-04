import type {
  ActivityEntry, AuditEntry, Customer, CustomerDetail, Invoice, RunDetail, RunEvent, RunSummary, Scenario,
  Stats, SystemInfo, Ticket, ToolSpec,
} from "../types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  system: () => request<SystemInfo>("/api/system"),
  stats: () => request<Stats>("/api/stats"),
  tools: () => request<ToolSpec[]>("/api/tools"),
  resetCrm: () => post<{ status: string }>("/api/admin/reset"),

  customers: (p: { q?: string; status?: string; risk_level?: string } = {}) => request<Customer[]>(`/api/customers${qs(p)}`),
  customer: (id: number) => request<CustomerDetail>(`/api/customers/${id}`),
  updateCustomer: (id: number, body: Partial<Pick<Customer, "status" | "risk_level">>) =>
    patch<Customer>(`/api/customers/${id}`, body),

  invoices: (p: { status?: string; min_amount?: number; max_amount?: number; q?: string } = {}) =>
    request<Invoice[]>(`/api/invoices${qs(p)}`),
  tickets: (p: { status?: string; priority?: string; q?: string } = {}) => request<Ticket[]>(`/api/tickets${qs(p)}`),
  updateTicket: (id: number, body: Partial<Pick<Ticket, "priority" | "status">>) => patch<Ticket>(`/api/tickets/${id}`, body),
  activity: (p: { customer_id?: number; limit?: number } = {}) => request<ActivityEntry[]>(`/api/activity${qs(p)}`),
  audit: (p: { run_id?: string; limit?: number } = {}) => request<AuditEntry[]>(`/api/audit${qs(p)}`),

  createTask: (goal: string, options: Record<string, unknown> = {}) =>
    post<{ id: string; run_id: string | null }>("/api/tasks", { goal, options, run: true }),
  scenarios: () => request<Scenario[]>("/api/demo/scenarios"),
  runDemo: (scenario: string, auto_approve = false) =>
    post<{ id: string; run_id: string }>("/api/demo/run", { scenario, auto_approve }),

  runs: (limit = 50) => request<RunSummary[]>(`/api/runs${qs({ limit })}`),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  runEvents: (id: string, after = 0) => request<RunEvent[]>(`/api/runs/${id}/events${qs({ after })}`),
  runAudit: (id: string) => request<AuditEntry[]>(`/api/runs/${id}/audit`),
  approve: (id: string, by: string, comment?: string) => post(`/api/runs/${id}/approve`, { by, comment }),
  reject: (id: string, by: string, comment?: string) => post(`/api/runs/${id}/reject`, { by, comment }),
};

export function runSocketUrl(runId: string, after: number): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/runs/${runId}/ws?after=${after}`;
}
