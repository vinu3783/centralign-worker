"""Direct API/database tools against the simulated CRM."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Activity, Customer, Invoice, OutboxMessage, SupportTicket
from app.database.session import session_scope
from app.tools.base import (
    ErrorCode,
    MutationTarget,
    RiskLevel,
    StrictInput,
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
)

CustomerStatus = Literal["Active", "High Priority", "At Risk", "Inactive"]
RiskLevelValue = Literal["low", "medium", "high"]
InvoiceStatus = Literal["paid", "unpaid", "overdue"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high"]


# ------------------------------------------------------------- serializers

def customer_dict(c: Customer) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "company": c.company, "email": c.email,
            "status": c.status, "risk_level": c.risk_level}


def invoice_dict(i: Invoice) -> dict[str, Any]:
    days_overdue = max((date.today() - i.due_date).days, 0) if i.status == "overdue" else 0
    return {"id": i.id, "invoice_number": i.invoice_number, "customer_id": i.customer_id,
            "customer_name": i.customer.company if i.customer else None, "amount": i.amount,
            "due_date": i.due_date.isoformat(), "status": i.status, "days_overdue": days_overdue}


def ticket_dict(t: SupportTicket) -> dict[str, Any]:
    return {"id": t.id, "customer_id": t.customer_id,
            "customer_name": t.customer.company if t.customer else None, "subject": t.subject,
            "priority": t.priority, "status": t.status}


def activity_dict(a: Activity) -> dict[str, Any]:
    return {"id": a.id, "customer_id": a.customer_id, "action": a.action, "actor": a.actor,
            "timestamp": a.timestamp.isoformat() if a.timestamp else None, "metadata": a.meta or {}}


def _as_list(v: Any) -> list[Any] | None:
    if v is None:
        return None
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _commit(db: Session, ctx: ToolContext) -> None:
    """Commit, unless the fault injector simulates a silently lost write."""
    if ctx.lose_write:
        db.rollback()
    else:
        db.commit()


def _get_customer(db: Session, customer_id: int) -> Customer:
    c = db.get(Customer, customer_id)
    if c is None:
        raise ToolError(ErrorCode.NOT_FOUND, f"Customer {customer_id} does not exist")
    return c


# ------------------------------------------------------------------ reads

class SearchInvoicesInput(StrictInput):
    status: InvoiceStatus | list[InvoiceStatus] | None = Field(
        None, description="'unpaid' = not yet due, 'overdue' = unpaid and past due, 'paid'.")
    amount_gt: float | None = Field(None, ge=0, description="Amount strictly greater than (INR).")
    amount_gte: float | None = Field(None, ge=0)
    amount_lt: float | None = Field(None, ge=0)
    amount_lte: float | None = Field(None, ge=0)
    customer_ids: list[int] | None = Field(None, max_length=500)
    invoice_ids: list[int] | None = Field(None, max_length=500)
    due_before: date | None = None
    due_after: date | None = None
    limit: int = Field(200, ge=1, le=500)


class SearchInvoices(Tool):
    name = "search_invoices"
    description = "Search invoices by status, amount range, customer and due date. Returns invoice records incl. customer_id and customer_name."
    input_model = SearchInvoicesInput
    entity = "invoice"
    filter_semantics = {
        "status": ("status", "in"), "amount_gt": ("amount", "greater_than"),
        "amount_gte": ("amount", "greater_or_equal"), "amount_lt": ("amount", "less_than"),
        "amount_lte": ("amount", "less_or_equal"), "customer_ids": ("customer_id", "in"),
        "invoice_ids": ("id", "in"), "due_before": ("due_date", "less_than"),
        "due_after": ("due_date", "greater_than"),
    }

    def execute(self, args: SearchInvoicesInput, ctx: ToolContext) -> ToolResult:
        q = select(Invoice).options(joinedload(Invoice.customer)).order_by(Invoice.id)
        if (statuses := _as_list(args.status)) is not None:
            q = q.where(Invoice.status.in_(statuses))
        if args.amount_gt is not None:
            q = q.where(Invoice.amount > args.amount_gt)
        if args.amount_gte is not None:
            q = q.where(Invoice.amount >= args.amount_gte)
        if args.amount_lt is not None:
            q = q.where(Invoice.amount < args.amount_lt)
        if args.amount_lte is not None:
            q = q.where(Invoice.amount <= args.amount_lte)
        if args.customer_ids is not None:
            q = q.where(Invoice.customer_id.in_(args.customer_ids))
        if args.invoice_ids is not None:
            q = q.where(Invoice.id.in_(args.invoice_ids))
        if args.due_before is not None:
            q = q.where(Invoice.due_date < args.due_before)
        if args.due_after is not None:
            q = q.where(Invoice.due_date > args.due_after)
        with session_scope() as db:
            rows = [invoice_dict(i) for i in db.scalars(q.limit(args.limit)).unique()]
        return self.ok(rows, total_amount=round(sum(r["amount"] for r in rows), 2))


class GetInvoiceInput(StrictInput):
    invoice_id: int = Field(ge=1)


class GetInvoice(Tool):
    name = "get_invoice"
    description = "Fetch a single invoice by id."
    input_model = GetInvoiceInput
    entity = "invoice"

    def execute(self, args: GetInvoiceInput, ctx: ToolContext) -> ToolResult:
        with session_scope() as db:
            inv = db.get(Invoice, args.invoice_id)
            if inv is None:
                raise ToolError(ErrorCode.NOT_FOUND, f"Invoice {args.invoice_id} does not exist")
            return self.ok(invoice_dict(inv))


class SearchCustomersInput(StrictInput):
    ids: list[int] | None = Field(None, max_length=500, description="Restrict to these customer ids.")
    status: CustomerStatus | list[CustomerStatus] | None = None
    risk_level: RiskLevelValue | list[RiskLevelValue] | None = None
    query: str | None = Field(None, max_length=100, description="Free-text match on name/company/email, or '#<id>'.")
    limit: int = Field(200, ge=1, le=500)


class SearchCustomers(Tool):
    name = "search_customers"
    description = "Search customers by ids, status, risk level or text. Use ids=[...] to resolve customers referenced by invoices/tickets."
    input_model = SearchCustomersInput
    entity = "customer"
    filter_semantics = {"ids": ("id", "in"), "status": ("status", "in"), "risk_level": ("risk_level", "in")}

    def execute(self, args: SearchCustomersInput, ctx: ToolContext) -> ToolResult:
        q = select(Customer).order_by(Customer.id)
        if args.ids is not None:
            q = q.where(Customer.id.in_(args.ids))
        if (statuses := _as_list(args.status)) is not None:
            q = q.where(Customer.status.in_(statuses))
        if (risks := _as_list(args.risk_level)) is not None:
            q = q.where(Customer.risk_level.in_(risks))
        if args.query:
            text = args.query.strip()
            if text.startswith("#") and text[1:].isdigit():
                q = q.where(Customer.id == int(text[1:]))
            else:
                like = f"%{text}%"
                q = q.where(or_(Customer.name.ilike(like), Customer.company.ilike(like), Customer.email.ilike(like)))
        with session_scope() as db:
            rows = [customer_dict(c) for c in db.scalars(q.limit(args.limit))]
        return self.ok(rows)


class GetCustomerInput(StrictInput):
    customer_id: int = Field(ge=1)


class GetCustomer(Tool):
    name = "get_customer"
    description = "Fetch a single customer by id."
    input_model = GetCustomerInput
    entity = "customer"

    def execute(self, args: GetCustomerInput, ctx: ToolContext) -> ToolResult:
        with session_scope() as db:
            return self.ok(customer_dict(_get_customer(db, args.customer_id)))


class SearchTicketsInput(StrictInput):
    status: TicketStatus | list[TicketStatus] | None = None
    priority: TicketPriority | list[TicketPriority] | None = None
    customer_ids: list[int] | None = Field(None, max_length=500)
    limit: int = Field(200, ge=1, le=500)


class SearchTickets(Tool):
    name = "search_tickets"
    description = "Search support tickets by status, priority and customer. Returns ticket records incl. customer_id."
    input_model = SearchTicketsInput
    entity = "ticket"
    filter_semantics = {"status": ("status", "in"), "priority": ("priority", "in"),
                        "customer_ids": ("customer_id", "in")}

    def execute(self, args: SearchTicketsInput, ctx: ToolContext) -> ToolResult:
        q = select(SupportTicket).options(joinedload(SupportTicket.customer)).order_by(SupportTicket.id)
        if (statuses := _as_list(args.status)) is not None:
            q = q.where(SupportTicket.status.in_(statuses))
        if (prios := _as_list(args.priority)) is not None:
            q = q.where(SupportTicket.priority.in_(prios))
        if args.customer_ids is not None:
            q = q.where(SupportTicket.customer_id.in_(args.customer_ids))
        with session_scope() as db:
            rows = [ticket_dict(t) for t in db.scalars(q.limit(args.limit)).unique()]
        return self.ok(rows)


class GetActivityInput(StrictInput):
    customer_id: int | None = Field(None, ge=1)
    limit: int = Field(50, ge=1, le=200)


class GetActivity(Tool):
    name = "get_activity"
    description = "Read the CRM activity history, optionally for one customer."
    input_model = GetActivityInput
    entity = "activity"

    def execute(self, args: GetActivityInput, ctx: ToolContext) -> ToolResult:
        q = select(Activity).order_by(Activity.timestamp.desc())
        if args.customer_id is not None:
            q = q.where(Activity.customer_id == args.customer_id)
        with session_scope() as db:
            return self.ok([activity_dict(a) for a in db.scalars(q.limit(args.limit))])


# ----------------------------------------------------------------- writes

class UpdateCustomerStatusInput(StrictInput):
    customer_id: int = Field(ge=1)
    status: CustomerStatus
    reason: str | None = Field(None, max_length=300)


def apply_customer_status(db: Session, customer_id: int, status: str, *, actor: str,
                          run_id: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """Single source of truth for status changes (used by the agent tool and the CRM API)."""
    customer = _get_customer(db, customer_id)
    before = customer.status
    changed = before != status
    if changed:
        customer.status = status
        db.add(Activity(customer_id=customer_id, action=f"Status changed: {before} → {status}", actor=actor,
                        meta={"field": "status", "before": before, "after": status, "run_id": run_id, "reason": reason}))
    return {"customer_id": customer_id, "label": customer.company, "field": "status",
            "before": before, "after": status, "changed": changed}


class UpdateCustomerStatus(Tool):
    name = "update_customer_status"
    description = "Change a customer's CRM status (Active, High Priority, At Risk, Inactive). Records an activity entry."
    input_model = UpdateCustomerStatusInput
    risk_level = RiskLevel.MEDIUM
    kind = "write"
    entity = "customer"

    def execute(self, args: UpdateCustomerStatusInput, ctx: ToolContext) -> ToolResult:
        with session_scope() as db:
            change = apply_customer_status(db, args.customer_id, args.status, actor=ctx.actor,
                                           run_id=ctx.run_id, reason=args.reason)
            _commit(db, ctx)
        return self.ok(change)

    def mutation_target(self, args: UpdateCustomerStatusInput) -> MutationTarget:
        return MutationTarget(entity="customer", entity_id=args.customer_id, field="status", desired=args.status)


class UpdateTicketPriorityInput(StrictInput):
    ticket_id: int = Field(ge=1)
    priority: TicketPriority


def apply_ticket_priority(db: Session, ticket_id: int, priority: str, *, actor: str,
                          run_id: str | None = None) -> dict[str, Any]:
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise ToolError(ErrorCode.NOT_FOUND, f"Ticket {ticket_id} does not exist")
    before = ticket.priority
    changed = before != priority
    if changed:
        ticket.priority = priority
        db.add(Activity(customer_id=ticket.customer_id, action=f"Ticket #{ticket_id} priority: {before} → {priority}",
                        actor=actor, meta={"ticket_id": ticket_id, "field": "priority", "before": before,
                                           "after": priority, "run_id": run_id}))
    return {"ticket_id": ticket_id, "label": f"#{ticket_id} {ticket.subject}", "field": "priority",
            "before": before, "after": priority, "changed": changed}


class UpdateTicketPriority(Tool):
    name = "update_ticket_priority"
    description = "Change a support ticket's priority (low, medium, high)."
    input_model = UpdateTicketPriorityInput
    risk_level = RiskLevel.MEDIUM
    kind = "write"
    entity = "ticket"

    def execute(self, args: UpdateTicketPriorityInput, ctx: ToolContext) -> ToolResult:
        with session_scope() as db:
            change = apply_ticket_priority(db, args.ticket_id, args.priority, actor=ctx.actor, run_id=ctx.run_id)
            _commit(db, ctx)
        return self.ok(change)

    def mutation_target(self, args: UpdateTicketPriorityInput) -> MutationTarget:
        return MutationTarget(entity="ticket", entity_id=args.ticket_id, field="priority", desired=args.priority)


class RecordActivityInput(StrictInput):
    customer_id: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=300)


class RecordActivity(Tool):
    name = "record_activity"
    description = "Append an internal note to a customer's activity history (append-only, no customer-visible effect)."
    input_model = RecordActivityInput
    kind = "write"
    entity = "activity"

    def execute(self, args: RecordActivityInput, ctx: ToolContext) -> ToolResult:
        with session_scope() as db:
            _get_customer(db, args.customer_id)
            act = Activity(customer_id=args.customer_id, action=f"Note: {args.note}", actor=ctx.actor,
                           meta={"run_id": ctx.run_id})
            db.add(act)
            _commit(db, ctx)
            return self.ok({"activity_id": act.id, "customer_id": args.customer_id})


class SendCustomerEmailInput(StrictInput):
    customer_id: int = Field(ge=1)
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=2000)


class SendCustomerEmail(Tool):
    name = "send_customer_email"
    description = "Send an email to a customer (simulated: written to the outbox, never actually sent). External communication."
    input_model = SendCustomerEmailInput
    risk_level = RiskLevel.HIGH
    kind = "write"
    entity = "customer"

    def execute(self, args: SendCustomerEmailInput, ctx: ToolContext) -> ToolResult:
        with session_scope() as db:
            customer = _get_customer(db, args.customer_id)
            msg = OutboxMessage(customer_id=customer.id, to_email=customer.email, subject=args.subject,
                                body=args.body, run_id=ctx.run_id)
            db.add(msg)
            db.add(Activity(customer_id=customer.id, action=f"Email queued: {args.subject}", actor=ctx.actor,
                            meta={"run_id": ctx.run_id}))
            _commit(db, ctx)
            return self.ok({"message_id": msg.id, "customer_id": customer.id, "label": customer.company,
                            "to": customer.email})


CRM_TOOLS: list[Tool] = [
    SearchInvoices(), GetInvoice(), SearchCustomers(), GetCustomer(), SearchTickets(), GetActivity(),
    UpdateCustomerStatus(), UpdateTicketPriority(), RecordActivity(), SendCustomerEmail(),
]
