import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  authenticateShell,
  openCommandPaletteFromKeyboard,
} from "./shell-auth";

async function expectFocusToStayInside(
  page: Page,
  selector: string,
  tabCount: number,
): Promise<void> {
  for (let index = 0; index < tabCount; index += 1) {
    await expect
      .poll(() =>
        page.evaluate((overlaySelector) => {
          const activeElement = document.activeElement;
          return Boolean(activeElement?.closest(overlaySelector));
        }, selector),
      )
      .toBe(true);
    await page.keyboard.press("Tab");
  }

  await expect
    .poll(() =>
      page.evaluate((overlaySelector) => {
        const activeElement = document.activeElement;
        return Boolean(activeElement?.closest(overlaySelector));
      }, selector),
    )
    .toBe(true);
}

test("desktop navigation activates routes and marks the active destination", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/study");

  const navigation = page.getByRole("navigation", {
    name: "Primary navigation",
  });
  await expect(navigation.getByRole("link", { name: "Study" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await navigation.getByRole("link", { name: "Dashboard" }).click();

  await expect(page).toHaveURL(/\/app\/dashboard$/);
  await expect(
    navigation.getByRole("link", { name: "Dashboard" }),
  ).toHaveAttribute("aria-current", "page");
});

test("mobile drawer exposes the same destinations and navigates without overflow", async ({
  page,
}) => {
  await page.setViewportSize({ height: 720, width: 320 });
  await authenticateShell(page);
  await page.goto("/app/dashboard");

  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Study" })).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Settings" })).toBeVisible();

  await drawer.getByRole("link", { name: "Settings" }).click();

  await expect(page).toHaveURL(/\/app\/settings$/);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth + 1,
      ),
    )
    .toBe(true);
});

test("mobile drawer keeps keyboard focus inside until dismissed", async ({
  page,
}) => {
  await page.setViewportSize({ height: 720, width: 320 });
  await authenticateShell(page);
  await page.goto("/app/dashboard");

  const trigger = page.getByRole("button", { name: "Open navigation" });
  await trigger.focus();
  await trigger.click();

  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer).toBeVisible();
  await expectFocusToStayInside(page, "#mobile-navigation-drawer", 8);

  await page.keyboard.press("Escape");

  await expect(drawer).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("command palette opens from the keyboard and activates a route", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/study");

  await openCommandPaletteFromKeyboard(page);
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();

  await page.getByLabel("Search commands").fill("settings");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/app\/settings$/);
});

test("command palette keeps keyboard focus inside until dismissed", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/study");

  const trigger = page.getByRole("button", { name: /Search/ });
  await openCommandPaletteFromKeyboard(page);

  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await expect(page.getByLabel("Search commands")).toBeFocused();

  await expectFocusToStayInside(page, "#command-palette", 9);

  await page.keyboard.press("Escape");

  await expect(palette).toBeHidden();
  await expect(trigger).toBeFocused();
});
