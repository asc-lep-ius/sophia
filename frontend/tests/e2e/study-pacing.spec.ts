import { expect, test, type Page } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

/**
 * Write an answer and prove the page actually received it.
 *
 * `fill` acts on the server-rendered textarea, which exists before Svelte has
 * hydrated and attached its input listener. On a loaded runner the write can
 * land in that window: the DOM holds the text, the store never hears about it,
 * and the elaboration floor is never met — the reveal then stays disabled
 * until the test times out, which is how this first showed up in CI and never
 * locally. Retrying until the "more characters" hint clears is what proves the
 * store has the text rather than just the DOM.
 */
async function writeAnswer(page: Page, text: string): Promise<void> {
  const field = page.getByLabel("Your answer");
  await expect(async () => {
    await field.fill(text);
    await expect(
      page.getByText(/more characters of your own answer/),
    ).toBeHidden({ timeout: 1000 });
  }).toPass({ timeout: 20_000 });
}

/**
 * The productive-friction gate.
 *
 * Every assertion here is a pedagogy requirement that a latency optimisation
 * would be tempted to remove: the elaboration floor before a reveal, the
 * un-skippable pre-test, and the reflection pause before results. If a change
 * makes the study surface faster by shortening one of these, this file is
 * meant to fail — that is its whole job.
 */

// Paced ids (< 100) get production's floors; one per test, because a graded
// card changes the deck the next test would see.
const ELABORATION_SESSION = 11;
const DWELL_SESSION = 12;
const PREDICT_SESSION = 13;
const REFLECT_SESSION = 14;
const COUNTDOWN_SESSION = 15;
const SETTLE_SESSION = 16;
const SHORT_ANSWER = "Too short.";
const FULL_ANSWER =
  "A minimum cut partitions the vertices so that every path from source to sink crosses it, which is why its capacity bounds the flow.";

test("the reveal waits for the learner's own elaboration", async ({ page }) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${ELABORATION_SESSION}/act`);

  const reveal = page.getByRole("button", { name: "Reveal" });
  await expect(reveal).toBeDisabled();

  await page.getByLabel("Your answer").fill(SHORT_ANSWER);
  await expect(reveal).toBeDisabled();
  // The exact remaining count, not merely that a hint exists: an unhydrated
  // page still renders the hint for an empty answer, so a write the store
  // never received would satisfy a looser assertion for the wrong reason.
  await expect(
    page.getByText(new RegExp(`${80 - SHORT_ANSWER.length} more characters`)),
  ).toBeVisible();
});

test("the reveal waits for the prompt dwell floor as well", async ({
  page,
}) => {
  await authenticateShell(page);
  const openedAt = Date.now();
  await page.goto(`/app/study/${DWELL_SESSION}/act`);
  await writeAnswer(page, FULL_ANSWER);

  const reveal = page.getByRole("button", { name: "Reveal" });
  if (Date.now() - openedAt < 5000) {
    await expect(reveal).toBeDisabled();
  }

  await expect(reveal).toBeEnabled({ timeout: 10_000 });
  expect(Date.now() - openedAt).toBeGreaterThanOrEqual(5000);
});

test("studying cannot start before a prediction and a pre-test answer", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${PREDICT_SESSION}/predict`);

  const start = page.getByRole("button", { name: "Start studying" });
  await expect(start).toBeDisabled();

  await page.getByRole("radio", { name: "Somewhat" }).check();
  await expect(start).toBeDisabled();
  await expect(
    page.getByText(/Record a prediction and a pre-test answer/),
  ).toBeVisible();
});

test("results stay closed for the server's reflection floor", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.goto(`/app/study/${REFLECT_SESSION}/reflect`);

  await writeAnswer(page, FULL_ANSWER);
  await expect(page.getByRole("button", { name: "Reveal" })).toBeEnabled({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Reveal" }).click();
  await page.getByRole("button", { name: "Good" }).click();

  const reflection = page.getByLabel(/Which part still feels unfinished/);
  await expect(reflection).toBeVisible();
  await reflection.fill("The cut argument finally makes sense to me.");

  const showResults = page.getByRole("button", { name: "Show my results" });
  await expect(showResults).toBeDisabled();
  await expect(page.getByText(/The results open in \d+ seconds/)).toBeVisible();
});

test("the reflection countdown is the server's number, not a client constant", async ({
  page,
}) => {
  await authenticateShell(page);
  const pacing = await page.request.get(
    "http://127.0.0.1:8788/api/study/pacing",
  );
  const { reflection_min_seconds: floor } = await pacing.json();

  await page.goto(`/app/study/${COUNTDOWN_SESSION}/reflect`);
  await writeAnswer(page, FULL_ANSWER);
  await expect(page.getByRole("button", { name: "Reveal" })).toBeEnabled({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Reveal" }).click();
  await page.getByRole("button", { name: "Good" }).click();

  const countdown = page.getByText(/The results open in \d+ seconds/);
  await expect(countdown).toBeVisible();
  const announced = Number(
    (await countdown.textContent())?.match(/(\d+) seconds/)?.[1] ?? 0,
  );

  // The countdown starts when the reflection does, so it opens on exactly the
  // floor the server named rather than a number compiled into the client.
  expect(floor).toBeGreaterThanOrEqual(30);
  expect(announced).toBeGreaterThan(floor - 3);
  expect(announced).toBeLessThanOrEqual(floor);
});

test("continue waits for the pre-test grade to reach the server", async ({
  page,
}) => {
  // The pre-test is the one card that is never re-presented if its grade does
  // not land — the flow has moved past predict by then — so leaving on the
  // optimistic advance would drop it out of the pre→post comparison.
  await authenticateShell(page);
  await page.goto(`/app/study/${SETTLE_SESSION}/predict`);

  await page.getByRole("radio", { name: "Somewhat" }).check();
  await writeAnswer(page, FULL_ANSWER);
  await expect(page.getByRole("button", { name: "Reveal" })).toBeEnabled({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Reveal" }).click();
  await page.getByRole("button", { name: "Good" }).click();

  const start = page.getByRole("button", { name: "Start studying" });
  await expect(start).toBeDisabled();
  await expect(page.getByText("Saving your answer…")).toBeVisible();

  await expect(start).toBeEnabled({ timeout: 10_000 });
});
