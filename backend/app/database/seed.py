"""Deterministic, realistic seed data for the simulated CRM.

Due dates are relative to *today* so that "overdue" always means past-due,
no matter when the demo is run.

The data is shaped so the showcase tasks have non-trivial answers:
- exactly 4 unpaid invoices are > ₹50,000 (and one sits exactly at ₹50,000,
  which a correct "greater than" filter must exclude);
- three customers have more than one overdue invoice;
- five open high-priority tickets belong to four customers, one of whom is
  already "At Risk" (so a correct agent detects a no-op instead of re-writing).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database.models import Activity, Customer, Invoice, OutboxMessage, SupportTicket

CUSTOMERS = [
    # id, contact name, company, status, risk
    (1, "Aarav Mehta", "Acme Retail Pvt Ltd", "Active", "low"),
    (2, "Priya Sharma", "Beta Logistics Ltd", "Active", "medium"),
    (3, "Rohan Iyer", "Gamma Infotech", "Active", "low"),
    (4, "Sneha Kapoor", "Delta Foods", "Active", "medium"),
    (5, "Vikram Rao", "Epsilon Pharma", "Active", "high"),
    (6, "Ananya Gupta", "Zeta Textiles", "Inactive", "low"),
    (7, "Karthik Nair", "Eta Constructions", "Active", "medium"),
    (8, "Meera Joshi", "Theta Healthcare", "Active", "low"),
    (9, "Arjun Reddy", "Iota Motors", "At Risk", "high"),
    (10, "Divya Pillai", "Kappa Electronics", "Active", "low"),
    (11, "Rahul Verma", "Lambda Fintech", "Active", "medium"),
    (12, "Nisha Bhat", "Mu Hospitality", "Active", "low"),
    (13, "Siddharth Das", "Nu Agritech", "Active", "medium"),
    (14, "Kavya Menon", "Xi Education", "Active", "low"),
    (15, "Aditya Singh", "Omicron Energy", "Active", "high"),
    (16, "Ishita Banerjee", "Pi Media", "Active", "low"),
]

INVOICES = [
    # customer_id, amount (INR), status, due date offset in days from today
    # unpaid (not yet due)
    (1, 72500, "unpaid", 12),
    (3, 125000, "unpaid", 20),
    (7, 58900, "unpaid", 8),
    (11, 96400, "unpaid", 30),
    (4, 50000, "unpaid", 15),  # boundary: NOT > 50,000
    (2, 18200, "unpaid", 10),
    (6, 9400, "unpaid", 25),
    (10, 42000, "unpaid", 18),
    (14, 27500, "unpaid", 5),
    (16, 33300, "unpaid", 22),
    # overdue (unpaid and past due)
    (5, 84000, "overdue", -20),
    (5, 31500, "overdue", -45),
    (9, 45200, "overdue", -12),
    (9, 67800, "overdue", -33),
    (9, 12900, "overdue", -60),
    (8, 22400, "overdue", -9),
    (8, 15600, "overdue", -27),
    (2, 38700, "overdue", -15),
    (12, 54300, "overdue", -6),
    (13, 8900, "overdue", -40),
    # paid
    (1, 64000, "paid", -30),
    (3, 21000, "paid", -50),
    (4, 77500, "paid", -14),
    (6, 15800, "paid", -70),
    (7, 93000, "paid", -21),
    (10, 56200, "paid", -40),
    (11, 12000, "paid", -5),
    (12, 41000, "paid", -35),
    (14, 101500, "paid", -60),
    (15, 68300, "paid", -25),
    (16, 7400, "paid", -18),
    (13, 29900, "paid", -48),
    (15, 22100, "paid", -10),
]

TICKETS = [
    # customer_id, subject, priority, status, description
    (2, "Shipment tracking API returning 500s", "high", "open", "Tracking endpoint fails for ~30% of requests since Monday."),
    (9, "Payment gateway reconciliation failing", "high", "open", "Daily settlement file does not match gateway totals."),
    (9, "Dashboard login loop after SSO change", "high", "open", "Users are redirected back to login after Okta migration."),
    (10, "Bulk invoice export times out", "high", "open", "Exports above 5,000 rows never complete."),
    (15, "Meter data sync stopped overnight", "high", "open", "No readings ingested from 02:00 IST."),
    (1, "Request for GST breakdown on invoices", "medium", "open", "Finance team needs CGST/SGST split per line item."),
    (3, "Add two new admin users", "low", "open", "Please provision access for two new team members."),
    (5, "Batch traceability report missing lots", "high", "in_progress", "Lot numbers missing from monthly compliance report."),
    (7, "Site inspection checklist not saving", "high", "resolved", "Fixed in release 4.2.1."),
    (8, "Appointment reminders sent twice", "medium", "open", "Patients receive duplicate SMS reminders."),
    (11, "KYC webhook signature mismatch", "high", "closed", "Rotated signing secret; confirmed working."),
    (12, "Update billing address", "low", "open", "New registered office in Kochi."),
    (4, "Inventory sync delay", "medium", "in_progress", "Stock levels lag by ~2 hours."),
    (13, "Training session request", "low", "resolved", "Scheduled for next Tuesday."),
    (14, "Gradebook CSV import errors", "medium", "open", "Imports fail on names with apostrophes."),
    (6, "Account reactivation query", "low", "closed", "Customer will revisit next quarter."),
]


def _email(name: str, company: str) -> str:
    first = name.split()[0].lower()
    domain = company.lower().replace(" pvt ltd", "").replace(" ltd", "").replace(" ", "")
    return f"{first}@{domain}.example.com"


def reset_crm(db: Session) -> None:
    for model in (Activity, OutboxMessage, Invoice, SupportTicket, Customer):
        db.execute(delete(model))
    db.flush()


def seed_crm(db: Session, *, today: date | None = None) -> None:
    today = today or date.today()
    now = datetime.now(timezone.utc)
    for cid, name, company, status, risk in CUSTOMERS:
        db.add(Customer(id=cid, name=name, company=company, email=_email(name, company), status=status, risk_level=risk))
    db.flush()
    for i, (cid, amount, status, offset) in enumerate(INVOICES, start=1):
        db.add(
            Invoice(
                id=i,
                customer_id=cid,
                invoice_number=f"INV-{today.year}-{i:04d}",
                amount=float(amount),
                due_date=today + timedelta(days=offset),
                status=status,
                created_at=now - timedelta(days=45 - offset if offset < 0 else 30),
            )
        )
    for i, (cid, subject, priority, status, desc) in enumerate(TICKETS, start=1):
        db.add(
            SupportTicket(
                id=i, customer_id=cid, subject=subject, priority=priority, status=status,
                description=desc, created_at=now - timedelta(days=i),
            )
        )
    db.add(Activity(customer_id=9, action="Status changed: Active → At Risk", actor="anita.ops@centralign.example",
                    timestamp=now - timedelta(days=3), meta={"field": "status", "before": "Active", "after": "At Risk"}))
    db.add(Activity(customer_id=6, action="Status changed: Active → Inactive", actor="anita.ops@centralign.example",
                    timestamp=now - timedelta(days=12), meta={"field": "status", "before": "Active", "after": "Inactive"}))
    db.add(Activity(customer_id=1, action="Call logged: payment reminder", actor="rahul.ar@centralign.example",
                    timestamp=now - timedelta(days=1), meta={"channel": "phone"}))
    db.flush()


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(func.count()).select_from(Customer)):
        return False
    seed_crm(db)
    return True


def reseed(db: Session) -> None:
    reset_crm(db)
    seed_crm(db)
