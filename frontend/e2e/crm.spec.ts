import { expect, test } from "@playwright/test";
import { resetCrm, waitForTable } from "./helpers";

test.beforeEach(async ({ page }) => resetCrm(page));

test("navigates every CRM page", async ({ page }) => {
  await page.goto("/dashboard");
  for (const [nav, heading] of [["customers", "Customers"], ["invoices", "Invoices"], ["tickets", "Support tickets"],
    ["runs", "Runs"], ["activity", "Activity"], ["dashboard", "Dashboard"]]) {
    await page.getByTestId(`nav-${nav}`).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
  await expect(page.getByTestId("mode-indicator")).toContainText("DEMO MODE");
});

test("filters invoices and searches customers", async ({ page }) => {
  await page.goto("/invoices");
  await page.getByTestId("invoice-status-filter").selectOption("unpaid");
  await page.getByTestId("invoice-min-amount").fill("50000");
  await expect(page.locator("tbody tr[data-row]")).toHaveCount(4);

  await page.goto("/customers?q=%239");
  await waitForTable(page);
  await expect(page.locator("tbody tr[data-row]")).toHaveCount(1);
  await expect(page.getByTestId("customer-row-9")).toContainText("Iota Motors");
});

test("a human can change a customer's status and it is logged", async ({ page }) => {
  await page.goto("/customers");
  await waitForTable(page);
  await page.getByTestId("status-select-4").selectOption("At Risk");
  await page.getByTestId("status-save-4").click();
  await expect(page.getByTestId("status-badge-4")).toHaveText("At Risk");
  await page.goto("/activity");
  await expect(page.getByTestId("activity-list")).toContainText("Delta Foods · Status changed: Active → At Risk");
});
