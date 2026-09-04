import { expect, test, type Page } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

/**
 * The keyboard-flow latency gate.
 *
 * Measured with the browser's own `event` timing entries — the same input the
 * INP metric is built from — rather than `performance.now()` around the code
 * under test, because what is being promised is user-observable responsiveness,
 * not how fast a handler returns.
 *
 * The deck is the fixture's ungated 50-card session: the budget is a
 * navigation-interaction budget, and measuring it through a 5-second dwell
 * floor fifty times would measure the floor instead. `study-pacing.spec.ts`
 * holds the floors.
 */

// Ungated ids (>= 100), one per test: the budget is a navigation budget, and
// a shared deck would let one test's grades change another's card counts.
const LATENCY_SESSION = 201;
const KEYBOARD_SESSION = 202;
// The fixture gives this id a two-card deck: one anchor, one practice card.
const EXTEND_SESSION = 501;
const INTERACTION_BUDGET_MS = 50;
const CARDS_TO_WORK = 12;
const CPU_THROTTLE_RATE = 4;

test("keyboard-only study stays inside the interaction budget", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "CPU throttling is driven through CDP.",
  );

  await authenticateShell(page);
  const client = await page.context().newCDPSession(page);
  // A mid-range phone is roughly 4x slower than the CI machine; the budget is
  // meaningless on an unthrottled desktop.
  await client.send("Emulation.setCPUThrottlingRate", {
    rate: CPU_THROTTLE_RATE,
  });

  await page.goto(`/app/study/${LATENCY_SESSION}/act`);
  await expect(page.getByLabel("Your answer")).toBeVisible();
  await startInteractionRecording(page);

  for (let card = 0; card < CARDS_TO_WORK; card += 1) {
    await page.getByLabel("Your answer").fill("An answer for this card.");
    // Tab out first: shortcuts are deliberately inert inside the answer field,
    // so this is the flow a keyboard-only learner actually has.
    await page.keyboard.press("Tab");
    await page.keyboard.press(" ");
    await page.keyboard.press("3");
  }

  const durations = await readInteractionDurations(page);
  const interactionCount = await page.evaluate(
    () =>
      (performance as Performance & { interactionCount?: number })
        .interactionCount ?? 0,
  );
  await client.send("Emulation.setCPUThrottlingRate", { rate: 1 });

  // The browser counted the interactions, so an empty duration list means they
  // were all faster than the observer's threshold — not that the observer
  // failed to attach or the page navigated out from under it.
  expect(interactionCount).toBeGreaterThan(0);
  expect(percentile(durations, 95)).toBeLessThan(INTERACTION_BUDGET_MS);
});

test("the whole session is reachable without a pointer", async ({ page }) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${KEYBOARD_SESSION}/act`);

  await page.getByLabel("Your answer").fill("An answer for this card.");
  await page.keyboard.press("Tab");
  await page.keyboard.press(" ");
  await expect(page.getByText("What you wrote")).toBeVisible();

  await page.keyboard.press("3");
  await expect(page.getByText(/Card 2 of \d+/)).toBeVisible();

  // Focus returns to the answer field with the next card, where shortcuts are
  // inert by design, so a keyboard learner tabs out to reach them again.
  await page.keyboard.press("Tab");
  await page.keyboard.press("f");
  await expect(
    page.getByRole("button", { name: "Focus mode on" }),
  ).toBeVisible();

  await page.keyboard.press("?");
  await expect(
    page.getByRole("dialog", { name: "Keyboard shortcuts" }),
  ).toBeVisible();
});

async function startInteractionRecording(page: Page): Promise<void> {
  await page.evaluate(() => {
    const durations: number[] = [];
    (window as unknown as { __interactions: number[] }).__interactions =
      durations;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        durations.push(entry.duration);
      }
    }).observe({ type: "event", buffered: true, durationThreshold: 16 });
  });
}

async function readInteractionDurations(page: Page): Promise<number[]> {
  return page.evaluate(
    () => (window as unknown as { __interactions: number[] }).__interactions,
  );
}

function percentile(values: number[], target: number): number {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.ceil((target / 100) * sorted.length) - 1;
  return sorted[Math.min(Math.max(index, 0), sorted.length - 1)] ?? 0;
}

test("a drained queue can be extended without leaving the session", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${EXTEND_SESSION}/act`);

  await page.getByLabel("Your answer").fill("The one card in this deck.");
  await page.getByRole("button", { name: "Reveal" }).click();
  await page.getByRole("button", { name: /Good/ }).click();
  await expect(page.getByText("No cards left in this session.")).toBeVisible();

  await page.getByRole("button", { name: "Add more cards" }).click();

  await expect(page.getByLabel("Your answer")).toBeVisible();
  await expect(page.getByText(/Card 1 of \d+/)).toBeVisible();
});
