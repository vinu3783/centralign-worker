"""CRM REST API used by the React UI (and by the browser tool, through the UI).

List endpoints reuse the agent's search tools so filtering logic exists once.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Activity, Customer, Invoice, OutboxMessage, SupportTicket
from app.database.session import get_db
from app.schemas.crm import CustomerUpdate, TicketUpdate
from app.tools.base import ToolContext, ToolError
from app.tools.crm_tools import (
    GetActivity,
    SearchCustomers,
    SearchInvoices,
    SearchTickets,
    activity_dict,
    apply_customer_status,
    apply_ticket_priority,
    customer_dict,
    invoice_dict,
    ticket_dict,
)

router = APIRouter(prefix="/api", tags=["crm"])
HUMAN_ACTOR = "Human operator (CRM UI)"


def _actor(x_actor: str | None) -> str:
    return (x_actor or HUMAN_ACTOR).strip()[:80] or HUMAN_ACTOR


def _run_tool(tool, **params: Any) -> list[dict[str, Any]]:
    try:
        args = tool.input_model.model_validate({k: v for k, v in params.items() if v is not None})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    result = tool.execute(args, ToolContext())
    return result.data


def _text_filter(rows: list[dict[str, Any]], q: str | None, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not q:
        return rows
    q = q.lower().strip()
    if q.startswith("#") and q[1:].isdigit():
        return [r for r in rows if r["id"] == int(q[1:])]
    return [r for r in rows if any(q in str(r.get(f, "")).lower() for f in fields)]


# -------------------------------------------------------------- customers

@router.get("/customers")
def list_customers(q: str | None = None, status: str | None = None, risk_level: str | None = None,
                   db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = _run_tool(SearchCustomers(), query=q, status=status, risk_level=risk_level, limit=500)
    outstanding = dict(db.execute(select(Invoice.customer_id, func.sum(Invoice.amount))
                                  .where(Invoice.status != "paid").group_by(Invoice.customer_id)).all())
    open_tickets = dict(db.execute(select(SupportTicket.customer_id, func.count())
                                   .where(SupportTicket.status.in_(["open", "in_progress"]))
                                   .group_by(SupportTicket.customer_id)).all())
    for r in rows:
        r["outstanding"] = float(outstanding.get(r["id"], 0))
        r["open_tickets"] = int(open_tickets.get(r["id"], 0))
    return rows


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(404, "Customer not found")
    acts = db.scalars(select(Activity).where(Activity.customer_id == customer_id)
                      .order_by(Activity.timestamp.desc()).limit(50))
    return {**customer_dict(c), "invoices": [invoice_dict(i) for i in c.invoices],
            "tickets": [ticket_dict(t) for t in c.tickets], "activity": [activity_dict(a) for a in acts]}


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: int, body: CustomerUpdate, db: Session = Depends(get_db),
                    x_actor: str | None = Header(None), x_run_id: str | None = Header(None)) -> dict[str, Any]:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(404, "Customer not found")
    actor = _actor(x_actor)
    try:
        if body.status is not None:
            apply_customer_status(db, customer_id, body.status, actor=actor, run_id=x_run_id or None)
        if body.risk_level is not None and body.risk_level != c.risk_level:
            db.add(Activity(customer_id=customer_id, action=f"Risk level changed: {c.risk_level} → {body.risk_level}",
                            actor=actor, meta={"field": "risk_level", "before": c.risk_level, "after": body.risk_level}))
            c.risk_level = body.risk_level
    except ToolError as exc:
        raise HTTPException(404, exc.message) from exc
    db.commit()
    db.refresh(c)
    return customer_dict(c)


# --------------------------------------------------------------- invoices

@router.get("/invoices")
def list_invoices(status: str | None = None, min_amount: float | None = Query(None, ge=0),
                  max_amount: float | None = Query(None, ge=0), customer_id: int | None = None,
                  q: str | None = None) -> list[dict[str, Any]]:
    rows = _run_tool(SearchInvoices(), status=status, amount_gt=min_amount, amount_lt=max_amount,
                     customer_ids=[customer_id] if customer_id else None, limit=500)
    return _text_filter(rows, q, ("invoice_number", "customer_name"))


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    return invoice_dict(inv)


# ---------------------------------------------------------------- tickets

@router.get("/tickets")
def list_tickets(status: str | None = None, priority: str | None = None, customer_id: int | None = None,
                 q: str | None = None) -> list[dict[str, Any]]:
    rows = _run_tool(SearchTickets(), status=status, priority=priority,
                     customer_ids=[customer_id] if customer_id else None, limit=500)
    return _text_filter(rows, q, ("subject", "customer_name"))


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, body: TicketUpdate, db: Session = Depends(get_db),
                  x_actor: str | None = Header(None)) -> dict[str, Any]:
    t = db.get(SupportTicket, ticket_id)
    if t is None:
        raise HTTPException(404, "Ticket not found")
    actor = _actor(x_actor)
    if body.priority is not None:
        apply_ticket_priority(db, ticket_id, body.priority, actor=actor)
    if body.status is not None and body.status != t.status:
        db.add(Activity(customer_id=t.customer_id, action=f"Ticket #{ticket_id} status: {t.status} → {body.status}",
                        actor=actor, meta={"ticket_id": ticket_id, "field": "status", "before": t.status,
                                           "after": body.status}))
        t.status = body.status
    db.commit()
    db.refresh(t)
    return ticket_dict(t)


# --------------------------------------------------------------- activity

@router.get("/activity")
def list_activity(customer_id: int | None = None, limit: int = Query(100, ge=1, le=200)) -> list[dict[str, Any]]:
    rows = _run_tool(GetActivity(), customer_id=customer_id, limit=limit)
    names = {c["id"]: c["company"] for c in _run_tool(SearchCustomers(), limit=500)}
    for r in rows:
        r["customer_name"] = names.get(r["customer_id"])
    return rows


@router.get("/outbox")
def list_outbox(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(OutboxMessage).order_by(OutboxMessage.id.desc()).limit(100))
    return [{"id": m.id, "customer_id": m.customer_id, "to": m.to_email, "subject": m.subject, "body": m.body,
             "run_id": m.run_id, "created_at": m.created_at.isoformat()} for m in rows]
