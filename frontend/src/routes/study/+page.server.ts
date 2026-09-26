import { fail, redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { apiFetch } from "../../hooks.server";
import type { components } from "$lib/api/schema";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import {
  readLearningPathChoice,
  readLearningPaths,
  selectedLearningPathId,
  type LearningPath,
} from "$lib/learningPath";
import { generateSessionDeck } from "$lib/server/studyDeck";
import type { Actions, PageServerLoad } from "./$types";

type SessionList = components["schemas"]["StudySessionListResponse"];
type StudySession = components["schemas"]["StudySessionItemResponse"];

/** The query flag that reopens the picker over an existing selection. */
const CHOOSE_PARAM = "choose";

export const load: PageServerLoad = async (event) => {
  const learningPathId = selectedLearningPathId(event.locals.tenant);

  // The list is a live TUWEL read, so it is only asked for when the picker is
  // on screen: a learner who has already chosen studies without waiting on it.
  if (learningPathId === null || event.url.searchParams.has(CHOOSE_PARAM)) {
    return {
      learningPathId,
      learningPaths: await loadLearningPaths(event),
      sessions: [] as StudySession[],
    };
  }

  return {
    learningPathId,
    learningPaths: null,
    sessions: await loadSessions(event, learningPathId),
  };
};

export const actions: Actions = {
  /**
   * Scope the session to the learning path the learner picked.
   *
   * It redirects rather than letting this request's load re-run, because the
   * tenant these locals were hydrated with predates the selection.
   */
  select: async (event) => {
    const learningPathId = readLearningPathChoice(
      await event.request.formData(),
    );
    if (learningPathId === null) {
      return fail(400, { error: "study.learning_path_required" });
    }

    const response = await apiFetch(event, "/api/learning-paths/selection", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ learning_path_id: learningPathId }),
    });
    if (!response.ok) {
      return fail(response.status, {
        error: "study.learning_path_select_failed",
      });
    }

    redirect(303, resolve("/study", {}));
  },

  /**
   * Starting a session is the one study mutation with no learner-process
   * trace behind it, so it stays a form action: it works before the page has
   * hydrated, and the redirect lands the learner on the predict route.
   */
  start: async (event) => {
    const learningPathId = selectedLearningPathId(event.locals.tenant);
    if (learningPathId === null) {
      return fail(409, { error: "study.learning_path_required" });
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

async function loadLearningPaths(
  event: Parameters<typeof apiFetch>[0],
): Promise<Panel<LearningPath[]>> {
  try {
    const response = await apiFetch(event, "/api/learning-paths");
    return await panelFromResponse(response, readLearningPaths, []);
  } catch {
    return unavailablePanel([]);
  }
}

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
