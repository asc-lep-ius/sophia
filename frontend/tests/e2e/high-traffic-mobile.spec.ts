import { expect, test, type Page } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

/**
 * Dashboard, quickstart and review on a phone.
 *
 * Two widths, not one: 375 px is the common phone, and 320 px is the narrowest
 * viewport WCAG 2.2's reflow criterion covers. A layout that fits the first and
 * not the second is a layout that fails for the learners least able to work
 * around it.
 */

const PHONE = { width: 375, height: 667 };
const NARROW = { width: 320, height: 667 };

const RECALL_ATTEMPT =
  "A recall attempt long enough to clear the elaboration floor the study " +
  "surface and this one share, written out from memory before checking.";

test.use({ viewport: PHONE, hasTouch: true });

for (const route of [
  "/app/dashboard",
  "/app/quickstart/welcome",
  "/app/quickstart/topics",
  "/app/quickstart/predict",
  "/app/review",
]) {
  test(`${route} fits a 375px phone and a 320px one`, async ({ page }) => {
    await authenticateShell(page);

    for (const viewport of [PHONE, NARROW]) {
      await page.setViewportSize(viewport);
      await page.goto(route);
      await expect(page.locator("main")).toBeVisible();
      await expectNoHorizontalOverflow(page);
    }
  });
}

test("the dashboard names one next action above everything else", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/dashboard");

  const nextAction = page.getByRole("region", { name: "Do this next" });
  await expect(nextAction).toBeVisible();

  // Above the panels, not buried under them: a decorative dashboard that hides
  // the next best study action is the anti-pattern this guards.
  const actionBox = await nextAction.boundingBox();
  const firstPanel = await page
    .getByRole("region", { name: "Due for review" })
    .boundingBox();
  expect(actionBox).not.toBeNull();
  expect(firstPanel).not.toBeNull();
  expect(actionBox!.y).toBeLessThan(firstPanel!.y);
});

test("a dashboard figure carries the same numbers as a table", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/dashboard");

  const week = page.getByRole("region", { name: "The week ahead" });
  await expect(week.getByRole("table")).toBeVisible();
  await expect(week.getByRole("rowheader", { name: "Today" })).toBeVisible();

  // The drawing repeats the table rather than adding to it, so a screen reader
  // that skips it misses nothing.
  await expect(week.locator("svg[aria-hidden='true']")).toHaveCount(1);
});

test("the dashboard keeps retired-scorer rows out of the calibration figure", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/dashboard");

  const calibration = page.getByRole("region", { name: "Calibration" });
  await expect(
    calibration.getByRole("rowheader", { name: "Graphs" }),
  ).toBeVisible();
  await expect(
    calibration.getByRole("rowheader", { name: "Hashing" }),
  ).toHaveCount(0);
  await expect(calibration.getByText(/are left out/)).toBeVisible();
});

test("quickstart can be completed on a phone, one URL per step", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto("/app/quickstart");

  await expect(page).toHaveURL(/\/app\/quickstart\/welcome$/);
  await page.getByRole("link", { name: "Continue" }).tap();

  await expect(page).toHaveURL(/\/app\/quickstart\/topics$/);
  await page.getByLabel("Topics you expect").fill("Graphs\nSorting");
  await page.getByRole("button", { name: "Save topics" }).tap();

  await expect(page).toHaveURL(/\/app\/quickstart\/predict$/);
  await expectNoHorizontalOverflow(page);
  await page.getByRole("radio", { name: "Somewhat" }).first().check();
  await page.getByRole("button", { name: "Save predictions" }).tap();

  await expect(page).toHaveURL(/\/app\/quickstart\/done$/);
  await expect(page.getByRole("heading", { name: "Set up" })).toBeVisible();
});

test("a reloaded quickstart step stays on that step", async ({ page }) => {
  await authenticateShell(page);
  await page.goto("/app/quickstart/predict");
  await page.reload();

  // The URL is the wizard's only state, so a reload cannot lose progress and
  // no other session can be handed it.
  await expect(page).toHaveURL(/\/app\/quickstart\/predict$/);
  await expect(page.getByRole("heading", { name: "Predict" })).toBeVisible();
});

test("a review can be worked by tap alone", async ({ page }) => {
  await authenticateShell(page);
  await page.goto("/app/review");

  await page.getByLabel("Your answer").fill(RECALL_ATTEMPT);
  const reveal = page.getByRole("button", { name: "Check myself" });
  await expect(reveal).toBeEnabled({ timeout: 10000 });
  await reveal.tap();
  await expect(page.getByText("What you wrote")).toBeVisible();

  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: /Good/ }).tap();
  await expect(page.getByText("Topic 2 of 2")).toBeVisible();
});

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const offenders = Array.from(document.querySelectorAll("body *"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          className: element.className.toString(),
          tagName: element.tagName.toLowerCase(),
          width: rect.width,
          x: rect.x,
        };
      })
      .filter(
        (entry) =>
          entry.width > 0 &&
          (entry.x < -1 || entry.x + entry.width > viewportWidth + 1),
      );

    return {
      offenders,
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth,
    };
  });

  expect(overflow.pageWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
  expect(overflow.offenders).toEqual([]);
}
