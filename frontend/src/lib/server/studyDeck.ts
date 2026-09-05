import { apiFetch } from "../../hooks.server";

export const GENERATED_BATCH_SIZE = 5;

/**
 * Fill a session's deck with a fresh batch of generated cards.
 *
 * Only ever called from an action — never from a `load`. The session layout's
 * load runs on hover preloading, so generating there would bill a model call
 * for every session a learner's mouse passes over. Safe to call again: a
 * second batch extends the deck rather than replacing it.
 *
 * Lives under `$lib/server` so SvelteKit refuses to bundle it into the
 * client, and so the two routes that need it can share one implementation —
 * `+page.server.ts` may only export SvelteKit's own names.
 */
export async function generateSessionDeck(
  event: Parameters<typeof apiFetch>[0],
  scope: { learningPathId: number; sessionId: number; topic: string },
): Promise<boolean> {
  const response = await apiFetch(event, "/api/study/questions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      learning_path_id: scope.learningPathId,
      topic: scope.topic,
      count: GENERATED_BATCH_SIZE,
      session_id: scope.sessionId,
    }),
  });
  return response.ok;
}
