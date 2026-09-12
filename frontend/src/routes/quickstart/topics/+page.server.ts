import { fail, redirect } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
import { parseTopicLines } from "$lib/quickstart/topics";
import type { Actions } from "./$types";

export const actions: Actions = {
  /**
   * Save the topics the learner named, then move on.
   *
   * A form action rather than a browser call so the step works before the page
   * has hydrated, and so what the learner typed is persisted by the API before
   * the next step asks them to rate it. Nothing about the wizard's progress is
   * held in the browser between the two steps.
   */
  save: async (event) => {
    const learningPathId = Number(event.locals.tenant.learning_path_id);
    if (!Number.isInteger(learningPathId) || learningPathId <= 0) {
      return fail(409, { error: "quickstart.no_learning_path" });
    }

    const form = await event.request.formData();
    const topics = parseTopicLines(String(form.get("topics") ?? ""));
    if (topics.length === 0) {
      return fail(400, { error: "quickstart.topics_required" });
    }

    const response = await apiFetch(event, "/api/quickstart/manual-topics", {
      body: JSON.stringify({ learning_path_id: learningPathId, topics }),
      headers: { "content-type": "application/json" },
      method: "POST",
    });
    if (!response.ok) {
      return fail(502, { error: "quickstart.save_failed" });
    }

    redirect(303, "/app/quickstart/predict");
  },
};
