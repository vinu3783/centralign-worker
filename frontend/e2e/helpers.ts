import { expect, type Page } from "@playwright/test";

export async function resetCrm(page: Page) {
  const res = await page.request.post("/api/admin/reset");
  expect(res.ok()).toBeTruthy();
}

export async function waitForTable(page: Page) {
  await page.locator("[data-testid=data-table][data-loading=false]").waitFor();
}
