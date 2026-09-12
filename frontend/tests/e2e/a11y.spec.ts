import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import {
  authenticateShell,
  openCommandPaletteFromKeyboard,
} from "./shell-auth";

const routes = [
  "/app/study",
  "/app/study/1/predict",
  "/app/study/1/act",
  "/app/study/1/reflect",
  "/app/dashboard",
  "/app/review",
  "/app/quickstart/welcome",
  "/app/quickstart/topics",
  "/app/quickstart/predict",
  "/app/quickstart/done",
  "/app/content",
  "/app/content/sources",
  "/app/topics",
  "/app/login",
  "/app/settings",
];

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

test("a revealed study card has no axe violations", async ({ page }) => {
  await authenticateShell(page);
  await page.goto("/app/study/401/act");
  await page.getByLabel("Your answer").fill("An answer long enough to reveal.");
  await page.getByRole("button", { name: "Reveal" }).click();
  await expect(page.getByText("What you wrote")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();

  expect(results.violations).toEqual([]);
});

test("a revealed review card has no axe violations", async ({ page }) => {
  await authenticateShell(page);
  await page.goto("/app/review");
  await page
    .getByLabel("Your answer")
    .fill(
      "A recall attempt long enough to clear the elaboration floor the study " +
        "surface and this one share, written out from memory.",
    );

  // The dwell floor is the study surface's, served rather than compiled in;
  // waiting it out is what the shared contract costs.
  const reveal = page.getByRole("button", { name: "Check myself" });
  await expect(reveal).toBeEnabled({ timeout: 10000 });
  await reveal.click();
  await expect(page.getByText("What you wrote")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();

  expect(results.violations).toEqual([]);
});

test("the study keyboard help dialog has no axe violations", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/study/401/act");
  await page.getByRole("button", { name: "Keyboard shortcuts" }).click();
  await expect(
    page.getByRole("dialog", { name: "Keyboard shortcuts" }),
  ).toBeVisible();

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
