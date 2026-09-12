import { fail, redirect } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
import { readConfidenceRatings } from "$lib/quickstart/topics";
import type { Actions } from "./$types";

export const actions: Actions = {
  /**
   * Record a confidence prediction per topic.
   *
   * The topics are re-read from the API inside the action rather than trusted
   * from the form: a submitted field naming a topic this learner never had is
   * not a prediction, and the ratings map is what the calibration comparison
   * is later built on.
   */
  save: async (event) => {
    const learningPathId = Number(event.locals.tenant.learning_path_id);
    if (!Number.isInteger(learningPathId) || learningPathId <= 0) {
      return fail(409, { error: "quickstart.no_learning_path" });
    }

    const form = await event.request.formData();
    const ratings = readConfidenceRatings(form, await knownTopics(event));
    if (Object.keys(ratings).length === 0) {
      return fail(400, { error: "quickstart.ratings_required" });
    }

    const response = await apiFetch(event, "/api/quickstart/confidence", {
      body: JSON.stringify({ learning_path_id: learningPathId, ratings }),
      headers: { "content-type": "application/json" },
      method: "POST",
    });
    if (!response.ok) {
      return fail(502, { error: "quickstart.save_failed" });
    }

    redirect(303, "/app/quickstart/done");
  },
};

async function knownTopics(
  event: Parameters<typeof apiFetch>[0],
): Promise<string[]> {
  const response = await apiFetch(event, "/api/quickstart/overview");
  if (!response.ok) {
    return [];
  }

  const body: unknown = await response.json();
  if (
    body === null ||
    typeof body !== "object" ||
    !Array.isArray((body as { topics?: unknown }).topics)
  ) {
    return [];
  }
  return (body as { topics: unknown[] }).topics
    .map((topic) =>
      topic !== null &&
      typeof topic === "object" &&
      typeof (topic as { topic?: unknown }).topic === "string"
        ? (topic as { topic: string }).topic
        : null,
    )
    .filter((topic): topic is string => topic !== null);
}
