import { error } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
import type { components } from "$lib/api/schema";
import type { LayoutServerLoad } from "./$types";

type SessionSummary = components["schemas"]["StudySessionSummaryResponse"];
type SessionQuestions =
  components["schemas"]["StudySessionQuestionListResponse"];
type Pacing = components["schemas"]["StudyPacingResponse"];

export const load: LayoutServerLoad = async (event) => {
  const sessionId = Number(event.params.sessionId);
  if (!Number.isInteger(sessionId) || sessionId <= 0) {
    error(404, "study.session_not_found");
  }

  const learningPathId = Number(event.locals.tenant.learning_path_id);
  if (!Number.isInteger(learningPathId) || learningPathId <= 0) {
    error(409, "study.learning_path_not_numeric");
  }

  const summary = await loadSummary(event, sessionId);
  const pacing = await loadPacing(event);
  const deck = await readQuestions(event, sessionId);

  return {
    attemptedQuestionIds: deck.attempted_question_ids,
    csrfToken: event.locals.csrfToken,
    learningPathId,
    pacing,
    questions: deck.questions,
    sessionId,
    summary,
  };
};

async function loadSummary(
  event: Parameters<typeof apiFetch>[0],
  sessionId: number,
): Promise<SessionSummary> {
  const response = await apiFetch(
    event,
    "/api/study/sessions/{session_id}/summary",
    { params: { session_id: sessionId } },
  );
  if (response.status === 404) {
    error(404, "study.session_not_found");
  }
  if (!response.ok) {
    error(502, "study.api_unavailable");
  }
  return (await response.json()) as SessionSummary;
}

async function loadPacing(
  event: Parameters<typeof apiFetch>[0],
): Promise<Pacing> {
  const response = await apiFetch(event, "/api/study/pacing");
  if (!response.ok) {
    error(502, "study.api_unavailable");
  }
  return (await response.json()) as Pacing;
}

/**
 * Read the session's deck. Nothing is generated here.
 *
 * This load runs on hover: `app.html` opts the whole app into SvelteKit's
 * hover preloading, so a learner sweeping the mouse across the session list
 * would otherwise bill a model call per session they never opened. Generation
 * belongs to the actions that a learner deliberately triggers — starting a
 * session, or extending a drained deck.
 */
async function readQuestions(
  event: Parameters<typeof apiFetch>[0],
  sessionId: number,
): Promise<SessionQuestions> {
  const response = await apiFetch(
    event,
    "/api/study/sessions/{session_id}/questions",
    { params: { session_id: sessionId } },
  );
  if (!response.ok) {
    // An empty deck rather than an error: the page can say "no cards" and
    // offer to generate some. The learning path is a placeholder nothing
    // reads — every route takes it from the session's own tenant.
    return {
      session_id: sessionId,
      learning_path_id: 0,
      questions: [],
      attempted_question_ids: [],
    };
  }
  return (await response.json()) as SessionQuestions;
}
