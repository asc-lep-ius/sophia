import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import {
  authenticateShell,
  openCommandPaletteFromKeyboard,
} from "./shell-auth";

const routes = ["/app/study", "/app/dashboard", "/app/login", "/app/settings"];

for (const route of routes) {
  test(`${route} has no axe violations`, async ({ page }) => {
    if (route !== "/app/login") {
      await authenticateShell(page);
    }
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();

    expect(results.violations).toEqual([]);
  });
}

test("populated mobile drawer shell state has no axe violations", async ({
  page,
}) => {
  await page.setViewportSize({ height: 720, width: 320 });
  await authenticateShell(page);
  await page.goto("/app/dashboard");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();

  expect(results.violations).toEqual([]);
});

test("populated command palette shell state has no axe violations", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/dashboard");
  await openCommandPaletteFromKeyboard(page);
  await expect(
    page.getByRole("dialog", { name: "Command palette" }),
  ).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();

  expect(results.violations).toEqual([]);
});
