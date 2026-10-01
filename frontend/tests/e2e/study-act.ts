import { expect, type Page } from "@playwright/test";

/**
 * Open the act route and return once it has hydrated.
 *
 * The card is server-rendered whole, with an enabled Reveal on the ungated
 * decks, and `goto` returns before `kit.start()` has finished hydrating. A
 * click, tap or key press in that window reaches a control with no handler,
 * and hydration then resets the textarea to the store's empty answer: nothing
 * is revealed and the text is gone, which is how these specs fail on a loaded
 * CI runner and never on a warm local run. `study-pacing.spec.ts` proves
 * hydration through the elaboration hint; ungated decks have no floor and so
 * no hint, so the proof here is the stream status, which the server renders as
 * `idle` and only the mounted page moves off it.
 */
export async function openHydratedAct(
  page: Page,
  sessionId: number,
): Promise<void> {
  await page.goto(`/app/study/${sessionId}/act`);
  await expect(page.locator(".stream")).not.toHaveAttribute(
    "data-status",
    "idle",
  );
}
