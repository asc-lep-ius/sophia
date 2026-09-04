import { expect, test } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

/**
 * Touch study on a small screen.
 *
 * Tap is the primary action throughout: WCAG 2.2's dragging-movements
 * criterion means a swipe may only ever be a shortcut for something a tap can
 * already do, and the grade targets have to clear 48 CSS pixels in the thumb
 * zone rather than sit in a row across the top of the screen.
 */

const LATENCY_SESSION = 2;
const MIN_TARGET_PX = 48;

test.use({ viewport: { width: 375, height: 667 }, hasTouch: true });

test("grades sit in a thumb-zone 2x2 grid with large enough targets", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${LATENCY_SESSION}/act`);
  await page.getByLabel("Your answer").fill("An answer written on a phone.");
  await page.getByRole("button", { name: "Reveal" }).tap();

  const grades = page.locator("[data-grade]");
  await expect(grades).toHaveCount(4);

  const boxes = [];
  for (let index = 0; index < 4; index += 1) {
    const box = await grades.nth(index).boundingBox();
    expect(box).not.toBeNull();
    boxes.push(box!);
  }

  for (const box of boxes) {
    expect(box.width).toBeGreaterThanOrEqual(MIN_TARGET_PX);
    expect(box.height).toBeGreaterThanOrEqual(MIN_TARGET_PX);
  }

  // Two rows of two: the first pair shares a row, the third starts a new one.
  expect(boxes[1]!.y).toBeCloseTo(boxes[0]!.y, 0);
  expect(boxes[2]!.y).toBeGreaterThan(boxes[0]!.y);
});

test("tap alone can work a card end to end", async ({ page }) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${LATENCY_SESSION}/act`);

  await page.getByLabel("Your answer").fill("An answer written on a phone.");
  await page.getByRole("button", { name: "Reveal" }).tap();
  await expect(page.getByText("What you wrote")).toBeVisible();

  await page.getByRole("button", { name: /Good/ }).tap();
  await expect(page.getByText("Card 2 of 50")).toBeVisible();
});

test("the card and its controls fit the viewport without sideways scrolling", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${LATENCY_SESSION}/act`);
  await page.getByLabel("Your answer").fill("An answer written on a phone.");
  await page.getByRole("button", { name: "Reveal" }).tap();

  const overflow = await page.evaluate(() => ({
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));

  expect(overflow.pageWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
});

test("the focused control is not hidden behind sticky chrome", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${LATENCY_SESSION}/act`);
  await page.getByLabel("Your answer").fill("An answer written on a phone.");

  const reveal = page.getByRole("button", { name: "Reveal" });
  await reveal.focus();
  const box = await reveal.boundingBox();

  expect(box).not.toBeNull();
  const hidden = await page.evaluate(
    ({ x, y, width, height }) => {
      const element = document.elementFromPoint(x + width / 2, y + height / 2);
      return element === null || !element.closest("button");
    },
    { x: box!.x, y: box!.y, width: box!.width, height: box!.height },
  );

  expect(hidden).toBe(false);
});
