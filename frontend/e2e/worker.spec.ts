import { expect, test } from "@playwright/test";
import { resetCrm, waitForTable } from "./helpers";

test.beforeEach(async ({ page }) => resetCrm(page));

test("demo: goal → plan → execution → failure → recovery → approval → verification → evidence", async ({ page }) => {
  await page.goto("/worker");
  await page.getByTestId("scenario-select").selectOption("standard");
  await page.getByTestId("run-demo").click();

  // Goal understanding + plan appear, then the run pauses for a human.
  await expect(page.getByTestId("goal-card")).toContainText("invoice.amount > ₹50,000");
  await expect(page.getByTestId("plan-card")).toContainText("update_customer_status");
  await expect(page.getByTestId("approval-card")).toBeVisible();
  await expect(page.getByTestId("approval-message")).toContainText("will modify 4 CRM record(s)");
  await expect(page.getByTestId("run-status")).toHaveText("awaiting approval");

  await page.getByTestId("approve-button").click();

  const timeline = page.getByTestId("timeline");
  await expect(timeline.locator("[data-type=retry]")).toContainText("retrying");
  await expect(timeline).toContainText("Recovered: call succeeded after 1 retry");
  await expect(page.getByTestId("result-headline")).toHaveText("Task completed successfully.", { timeout: 30_000 });
  await expect(page.getByTestId("result-lines")).toContainText("4 invoices found");
  await expect(page.getByTestId("result-lines")).toContainText("1 failure(s) detected and recovered");
  await expect(page.getByTestId("verification-card")).toContainText("PASS");
  await expect(page.getByTestId("evidence-row")).toHaveCount(4);
  await expect(page.getByTestId("retry-count")).toHaveText("1");
  await expect(page.getByTestId("phase-COMPLETE")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("phase-ADAPT")).toHaveAttribute("data-state", "adapt");

  // The CRM really changed.
  await page.goto("/customers");
  await waitForTable(page);
  for (const id of [1, 3, 7, 11]) await expect(page.getByTestId(`status-badge-${id}`)).toHaveText("High Priority");
  await expect(page.getByTestId("status-badge-4")).toHaveText("Active"); // exactly ₹50,000: excluded
});

test("rejecting the approval stops safely and changes nothing", async ({ page }) => {
  await page.goto("/worker");
  await page.getByTestId("example-1").click();
  await page.getByTestId("run-task").click();
  await expect(page.getByTestId("approval-card")).toBeVisible();
  await page.getByTestId("reject-button").click();
  await expect(page.getByTestId("result-headline")).toContainText("Stopped safely");
  await page.goto("/customers");
  await waitForTable(page);
  await expect(page.getByTestId("status-badge-1")).toHaveText("Active");
});

test("read-only task completes without approval and shows results", async ({ page }) => {
  await page.goto("/worker");
  await page.getByTestId("example-3").click();
  await page.getByTestId("run-task").click();
  await expect(page.getByTestId("result-headline")).toHaveText("Task completed successfully.");
  await expect(page.getByTestId("result-panel")).toContainText("Iota Motors");
  await expect(page.getByTestId("approval-card")).toHaveCount(0);
});

test("run details page shows metrics and audit log", async ({ page }) => {
  const res = await page.request.post("/api/demo/run", { data: { scenario: "lost_write", auto_approve: true } });
  const { run_id } = await res.json();
  await page.goto(`/runs/${run_id}`);
  await expect(page.getByTestId("result-headline")).toHaveText("Task completed successfully.", { timeout: 30_000 });
  await expect(page.getByTestId("result-lines")).toContainText("NOT persisted");
  await expect(page.getByTestId("run-metrics")).toContainText("Verification");
  await expect(page.getByTestId("audit-table")).toContainText("verify_outcome");
});
