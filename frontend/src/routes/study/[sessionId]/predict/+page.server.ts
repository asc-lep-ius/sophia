import { fail } from "@sveltejs/kit";
import { generateSessionDeck } from "$lib/server/studyDeck";
import type { Actions } from "./$types";

export const actions: Actions = {
  /**
   * Fill a deck the start action could not.
   *
   * Generation only ever happens on a deliberate press: a session whose
   * generation failed (or one started before this route existed) would
   * otherwise be a dead end, but putting the retry back in the page load would
   * hand hover preloading a way to spend model calls.
   */
  generate: async (event) => {
    const sessionId = Number(event.params.sessionId);
    const learningPathId = Number(event.locals.tenant.learning_path_id);
    const form = await event.request.formData();
    const topic = String(form.get("topic") ?? "").trim();

    if (
      !Number.isInteger(sessionId) ||
      !Number.isInteger(learningPathId) ||
      !topic
    ) {
      return fail(400, { error: "study.extend_failed" });
    }

    const generated = await generateSessionDeck(event, {
      learningPathId,
      sessionId,
      topic,
    });
    return generated
      ? { generated: true }
      : fail(502, { error: "study.extend_failed" });
  },
};
