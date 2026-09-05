import type { Page } from "@playwright/test";

const PREVIEW_ORIGIN = "http://127.0.0.1:4173";

export async function authenticateShell(page: Page): Promise<void> {
  await page.context().addCookies([
    { name: "sophia-e2e-auth", value: "1", url: PREVIEW_ORIGIN },
    { name: "sophia-org-id", value: "local", url: PREVIEW_ORIGIN },
    {
      // Numeric: the study API scopes every call on a learning path id, and
      // the placeholder the shell ships with is not one.
      name: "sophia-learning-path-id",
      value: "12",
      url: PREVIEW_ORIGIN,
    },
  ]);
}

export async function openCommandPaletteFromKeyboard(
  page: Page,
  triggerName: RegExp | string = /Search/,
): Promise<void> {
  await page.getByRole("button", { name: triggerName }).focus();
  await page.keyboard.press("Control+K");
}
