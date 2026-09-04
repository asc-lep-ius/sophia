import { expect, test } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

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
  await expect(
    page.getByText(/more characters of your own answer/),
  ).toBeVisible();
});

test("the reveal waits for the prompt dwell floor as well", async ({
  page,
}) => {
  await authenticateShell(page);
  const openedAt = Date.now();
  await page.goto(`/app/study/${DWELL_SESSION}/act`);
  await page.getByLabel("Your answer").fill(FULL_ANSWER);

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

  await page.getByLabel("Your answer").fill(FULL_ANSWER);
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
  await page.getByLabel("Your answer").fill(FULL_ANSWER);
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
