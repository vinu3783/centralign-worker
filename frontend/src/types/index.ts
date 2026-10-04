export type Json = Record<string, unknown>;

export interface Customer {
  id: number;
  name: string;
  company: string;
  email: string;
  status: CustomerStatus;
  risk_level: "low" | "medium" | "high";
  outstanding?: number;
  open_tickets?: number;
}
export type CustomerStatus = "Active" | "High Priority" | "At Risk" | "Inactive";
export const CUSTOMER_STATUSES: CustomerStatus[] = ["Active", "High Priority", "At Risk", "Inactive"];

export interface CustomerDetail extends Customer {
  invoices: Invoice[];
  tickets: Ticket[];
  activity: ActivityEntry[];
}

export interface Invoice {
  id: number;
  invoice_number: string;
  customer_id: number;
  customer_name: string | null;
  amount: number;
  due_date: string;
  status: "paid" | "unpaid" | "overdue";
  days_overdue: number;
}

export interface Ticket {
  id: number;
  customer_id: number;
  customer_name: string | null;
  subject: string;
  priority: "low" | "medium" | "high";
  status: "open" | "in_progress" | "resolved" | "closed";
}

export interface ActivityEntry {
  id: number;
  customer_id: number | null;
  customer_name?: string | null;
  action: string;
  actor: string;
  timestamp: string;
  metadata: Json;
}

export interface AuditEntry {
  id: number;
  run_id: string;
  timestamp: string;
  agent_step: string;
  tool: string | null;
  input: Json | null;
  output: Json | null;
  status: string;
  error: string | null;
  duration_ms: number | null;
}

export type RunStatus =
  | "running" | "awaiting_approval" | "verifying" | "completed" | "needs_attention"
  | "rejected" | "failed" | "needs_clarification";

export interface RunMetrics {
  duration_ms?: number;
  approval_wait_ms?: number;
  tool_calls?: number;
  successful_calls?: number;
  failed_calls?: number;
  retries?: number;
  recovered_failures?: number;
  approvals_requested?: number;
  records_changed?: number;
  tools_used?: string[];
  verification?: "pass" | "fail" | null;
  plan_source?: string | null;
}

export interface RunSummary {
  id: string;
  task_id: string;
  goal: string;
  status: RunStatus;
  mode: string;
  model: string;
  metrics: RunMetrics;
  verification_passed: boolean | null;
  started_at: string;
  finished_at: string | null;
}

export interface Condition { entity: string; field: string; operator: string; value: unknown }
export interface StructuredGoal {
  objective: string;
  primary_entity: string;
  entities: string[];
  conditions: Condition[];
  group_condition: { entity: string; by: string; min_count: number } | null;
  actions: { type: string; value: string | null; channel: string }[];
  required_actions: string[];
  ambiguities: string[];
  clarification_needed: string | null;
}

export interface PlanStep {
  id: string;
  description: string;
  tool: string;
  args: Json;
  for_each: string | null;
  items?: unknown[] | null;
  remediation_of?: string | null;
  risk?: string | null;
  kind?: string | null;
  channel?: string | null;
}
export interface Plan { steps: PlanStep[]; rationale: string; source: string }

export interface VerificationCheck {
  name: string;
  kind: string;
  expected: unknown;
  observed: unknown;
  passed: boolean;
  details: Json[];
}
export interface Verification { attempt: number; passed: boolean; checks: VerificationCheck[]; summary: string }

export interface EvidenceItem {
  id?: number;
  kind: string;
  entity: string | null;
  entity_id: number | null;
  label: string | null;
  field: string | null;
  before: unknown;
  after: unknown;
  verified: boolean | null;
  details: Json;
  timestamp: string;
  call_id?: string | null;
}

export interface ResultTable { title: string; entity: string | null; columns: string[]; rows: Json[] }

export interface FinalResult {
  status: RunStatus;
  headline: string;
  summary_lines: string[];
  changes: EvidenceItem[];
  results: ResultTable[];
  metrics: RunMetrics;
  verification: Verification | null;
}

export interface Approval {
  id: number;
  step_id: string;
  tool: string;
  risk_level: string;
  message: string;
  preview: Json[];
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  comment: string | null;
  requested_at: string;
  decided_at: string | null;
}

export interface LiveState {
  status: RunStatus;
  current_step: string | null;
  current_tool: string | null;
  completed_steps: string[];
  pending_steps: string[];
  step_runs: Record<string, { status: string; item_status: string[]; notes: string[]; preview: Json[] }>;
  retry_count: number;
  tool_calls: number;
  approval_status: string;
}

export interface RunDetail extends RunSummary {
  structured_goal: StructuredGoal | null;
  plan: Plan | null;
  final_result: FinalResult | null;
  error: string | null;
  approvals: Approval[];
  evidence: EvidenceItem[];
  live: LiveState | null;
}

export interface RunEvent {
  seq: number;
  run_id: string;
  type: string;
  timestamp: string;
  status?: "running" | "success" | "error" | "warning" | "info" | "waiting";
  node?: string;
  title?: string;
  detail?: string;
  step_id?: string;
  tool?: string;
  call_id?: string;
  attempt?: number;
  input?: Json;
  output?: unknown;
  metadata?: Json;
  error?: string;
  error_code?: string;
  retryable?: boolean;
  duration_ms?: number;
  injected_fault?: string | null;
  notes?: string[];
  expected?: string | null;
  actual?: string | null;
  message?: string;
  preview?: Json[];
  steps?: PlanStep[];
  goal?: StructuredGoal;
  checks?: VerificationCheck[];
  lines?: string[];
  final_status?: RunStatus;
  [key: string]: unknown;
}

export interface SystemInfo {
  mode: "demo" | "llm";
  model: string;
  approval_threshold: string;
  max_retries: number;
  browser_tools_enabled: boolean;
  tools: number;
}

export interface Stats {
  tasks_completed: number;
  tasks_failed: number;
  runs_total: number;
  avg_execution_ms: number | null;
  success_rate: number | null;
  human_approvals: number;
  pending_approvals: number;
  recovered_failures: number;
  crm: { customers: number; high_priority: number; at_risk: number; unpaid_amount: number; overdue_invoices: number; open_tickets: number };
  recent_runs: RunSummary[];
}

export interface Scenario { id: string; title: string; description: string; goal: string }
export interface ToolSpec { name: string; description: string; risk_level: string; kind: string; channel: string; input_schema: Json }
