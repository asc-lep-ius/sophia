import { fail } from "@sveltejs/kit";
import { apiFetch } from "../../../../hooks.server";
import type { Actions } from "./$types";

const GENERATED_BATCH_SIZE = 5;

export const actions: Actions = {
  /**
   * Generate another batch of cards for a session whose queue ran dry.
   *
   * A form action rather than a browser call: generation is a model round-trip
   * with no learner-process trace behind it, and the reload it causes is what
   * re-reads the extended question set through the layout load.
   */
  extend: async (event) => {
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

    const response = await apiFetch(event, "/api/study/questions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        learning_path_id: learningPathId,
        topic,
        count: GENERATED_BATCH_SIZE,
        session_id: sessionId,
      }),
    });
    if (!response.ok) {
      return fail(response.status, { error: "study.extend_failed" });
    }

    return { extended: true };
  },
};
