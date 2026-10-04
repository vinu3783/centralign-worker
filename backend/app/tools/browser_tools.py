"""Browser ("computer use") tools: drive the real CRM web UI with Playwright.

These operate the same React CRM a human uses, so they only work while the
frontend is running. Each write tool declares an API fallback, which the agent's
recovery logic uses if the browser channel is unavailable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field

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
from app.tools.crm_tools import CustomerStatus

NAV_TIMEOUT_MS = 15_000


class _Browser:
    """Short-lived headless browser session for one tool call."""

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise ToolError(ErrorCode.UNAVAILABLE, "Playwright is not installed", retryable=False) from exc
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=self.ctx.settings.browser_headless)
        except Exception as exc:
            self._pw.stop()
            raise ToolError(ErrorCode.UNAVAILABLE, f"Browser could not start: {str(exc).splitlines()[0]}",
                            retryable=False) from exc
        page = self._browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(NAV_TIMEOUT_MS)
        # Attribute UI-driven changes to the agent in the CRM activity log.
        page.set_extra_http_headers({"X-Actor": "CentrAlign Worker (browser)", "X-Run-Id": self.ctx.run_id or ""})
        return page

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()
        return False


def _goto(page, ctx: ToolContext, path: str) -> None:
    from playwright.sync_api import Error as PwError, TimeoutError as PwTimeout

    url = ctx.settings.frontend_url.rstrip("/") + path
    try:
        page.goto(url)
        page.wait_for_selector("[data-testid=data-table][data-loading=false]")
    except PwTimeout as exc:
        raise ToolError(ErrorCode.TIMEOUT, f"CRM page did not load in time: {path}") from exc
    except PwError as exc:
        raise ToolError(ErrorCode.UNAVAILABLE, f"CRM web UI unreachable at {url}", retryable=False) from exc


def _screenshot(page, ctx: ToolContext, name: str) -> str:
    folder = Path(ctx.settings.data_dir) / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{ctx.run_id or 'adhoc'}-{name}.png"
    page.screenshot(path=str(folder / fname))
    return f"/api/files/screenshots/{fname}"


class BrowserReadTableInput(StrictInput):
    page: Literal["customers", "invoices", "tickets"]
    search: str | None = Field(None, max_length=100)


class BrowserReadTable(Tool):
    name = "browser_read_table"
    description = "Open a CRM page in a real browser, optionally type a search, and read the visible table rows."
    input_model = BrowserReadTableInput
    channel = "browser"

    def execute(self, args: BrowserReadTableInput, ctx: ToolContext) -> ToolResult:
        with _Browser(ctx) as page:
            path = f"/{args.page}" + (f"?q={quote(args.search)}" if args.search else "")
            _goto(page, ctx, path)
            headers = [h.strip() for h in page.locator("[data-testid=data-table] thead th").all_inner_texts()]
            rows: list[dict[str, Any]] = []
            for tr in page.locator("[data-testid=data-table] tbody tr[data-row]").all():
                cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
                rows.append({h or f"col{i}": v for i, (h, v) in enumerate(zip(headers, cells))})
            shot = _screenshot(page, ctx, f"read-{args.page}")
        return self.ok(rows, page=args.page, screenshot=shot)


class BrowserUpdateCustomerStatusInput(StrictInput):
    customer_id: int = Field(ge=1)
    status: CustomerStatus


class BrowserUpdateCustomerStatus(Tool):
    name = "browser_update_customer_status"
    description = ("Change a customer's status by operating the CRM web UI (search, select, save) like a human would. "
                   "Falls back to update_customer_status if the UI is unavailable.")
    input_model = BrowserUpdateCustomerStatusInput
    risk_level = RiskLevel.MEDIUM
    kind = "write"
    channel = "browser"
    entity = "customer"
    fallback_tool = "update_customer_status"

    def execute(self, args: BrowserUpdateCustomerStatusInput, ctx: ToolContext) -> ToolResult:
        cid = args.customer_id
        with _Browser(ctx) as page:
            _goto(page, ctx, f"/customers?q={quote('#' + str(cid))}")
            row = page.locator(f"[data-testid=customer-row-{cid}]")
            if row.count() == 0:
                raise ToolError(ErrorCode.NOT_FOUND, f"Customer {cid} not visible in CRM UI")
            before = page.locator(f"[data-testid=status-badge-{cid}]").inner_text().strip()
            label = row.locator("[data-col=company]").inner_text().strip()
            page.select_option(f"[data-testid=status-select-{cid}]", args.status)
            page.click(f"[data-testid=status-save-{cid}]")
            try:
                page.wait_for_function(
                    "([sel, want]) => document.querySelector(sel)?.textContent.trim() === want",
                    arg=[f"[data-testid=status-badge-{cid}]", args.status],
                )
            except Exception as exc:
                raise ToolError(ErrorCode.TIMEOUT, "UI did not confirm the status change") from exc
            shot = _screenshot(page, ctx, f"customer-{cid}")
        return self.ok({"customer_id": cid, "label": label, "field": "status", "before": before,
                        "after": args.status, "changed": before != args.status}, screenshot=shot)

    def mutation_target(self, args: BrowserUpdateCustomerStatusInput) -> MutationTarget:
        return MutationTarget(entity="customer", entity_id=args.customer_id, field="status", desired=args.status)


BROWSER_TOOLS: list[Tool] = [BrowserReadTable(), BrowserUpdateCustomerStatus()]
