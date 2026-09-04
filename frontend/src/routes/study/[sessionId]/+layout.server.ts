import { error } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
import type { components } from "$lib/api/schema";
import type { LayoutServerLoad } from "./$types";

type SessionSummary = components["schemas"]["StudySessionSummaryResponse"];
type SessionQuestions =
  components["schemas"]["StudySessionQuestionListResponse"];
type Pacing = components["schemas"]["StudyPacingResponse"];

const GENERATED_BATCH_SIZE = 5;

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
  const questions = await loadQuestions(event, {
    sessionId,
    learningPathId,
    topic: summary.session.topic,
  });

  return {
    csrfToken: event.locals.csrfToken,
    learningPathId,
    pacing,
    questions,
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
 * Read the session's cards, generating one batch only when it has none.
 *
 * Generation is a model call: doing it on every load would make a reload cost
 * money and hand the learner a different deck half-way through a session.
 */
async function loadQuestions(
  event: Parameters<typeof apiFetch>[0],
  scope: { sessionId: number; learningPathId: number; topic: string },
): Promise<SessionQuestions["questions"]> {
  const existing = await readQuestions(event, scope.sessionId);
  if (existing.length > 0) {
    return existing;
  }

  const generated = await apiFetch(event, "/api/study/questions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      learning_path_id: scope.learningPathId,
      topic: scope.topic,
      count: GENERATED_BATCH_SIZE,
      session_id: scope.sessionId,
    }),
  });
  if (!generated.ok) {
    return [];
  }
  return await readQuestions(event, scope.sessionId);
}

async function readQuestions(
  event: Parameters<typeof apiFetch>[0],
  sessionId: number,
): Promise<SessionQuestions["questions"]> {
  const response = await apiFetch(
    event,
    "/api/study/sessions/{session_id}/questions",
    { params: { session_id: sessionId } },
  );
  if (!response.ok) {
    return [];
  }
  const body = (await response.json()) as SessionQuestions;
  return body.questions;
}
