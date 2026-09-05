import { fail, redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { apiFetch } from "../../hooks.server";
import type { components } from "$lib/api/schema";
import { generateSessionDeck } from "$lib/server/studyDeck";
import type { Actions, PageServerLoad } from "./$types";

type SessionList = components["schemas"]["StudySessionListResponse"];
type StudySession = components["schemas"]["StudySessionItemResponse"];

export const load: PageServerLoad = async (event) => {
  const learningPathId = Number(event.locals.tenant.learning_path_id);
  if (!Number.isInteger(learningPathId) || learningPathId <= 0) {
    return { learningPathId: null, sessions: [] as StudySession[] };
  }

  return {
    learningPathId,
    sessions: await loadSessions(event, learningPathId),
  };
};

export const actions: Actions = {
  /**
   * Starting a session is the one study mutation with no learner-process
   * trace behind it, so it stays a form action: it works before the page has
   * hydrated, and the redirect lands the learner on the predict route.
   */
  start: async (event) => {
    const learningPathId = Number(event.locals.tenant.learning_path_id);
    if (!Number.isInteger(learningPathId) || learningPathId <= 0) {
      return fail(409, { error: "study.learning_path_not_numeric" });
    }

    const form = await event.request.formData();
    const topic = String(form.get("topic") ?? "").trim();
    if (!topic) {
      return fail(400, { error: "study.topic_required" });
    }

    const response = await apiFetch(event, "/api/study/sessions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ learning_path_id: learningPathId, topic }),
    });
    if (!response.ok) {
      return fail(response.status, { error: "study.session_start_failed" });
    }

    const body = (await response.json()) as { session: StudySession };
    // Generate here rather than in the session layout's load: that load also
    // runs on hover preloading, which would bill a model call for every
    // session a learner's mouse passes over.
    await generateSessionDeck(event, {
      learningPathId,
      sessionId: body.session.id,
      topic,
    });
    redirect(
      303,
      resolve("/study/[sessionId]/predict", {
        sessionId: String(body.session.id),
      }),
    );
  },
};

async function loadSessions(
  event: Parameters<typeof apiFetch>[0],
  learningPathId: number,
): Promise<StudySession[]> {
  const response = await apiFetch(event, "/api/study/sessions", {
    query: { learning_path_id: learningPathId },
  });
  if (!response.ok) {
    return [];
  }
  const body = (await response.json()) as SessionList;
  return body.sessions;
}
