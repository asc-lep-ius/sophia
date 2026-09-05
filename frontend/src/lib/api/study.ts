import {
  createApiClient,
  unwrapApiResponse,
  type NormalizedApiError,
} from "$lib/api/client";
import type { components } from "$lib/api/schema";

export type StudySession = components["schemas"]["StudySessionItemResponse"];
export type StudyQuestion = components["schemas"]["Question"];
export type StudyAttempt = components["schemas"]["StudyAttemptItemResponse"];
export type StudySessionSummary =
  components["schemas"]["StudySessionSummaryResponse"];
export type StudyPacing = components["schemas"]["StudyPacingResponse"];
export type StudyAttemptPhase = components["schemas"]["StudyAttemptPhase"];
export type CalibrationBand = components["schemas"]["CalibrationBand"];
export type ElaborationPolicy = components["schemas"]["ElaborationPolicy"];
export type LearningEventInput = components["schemas"]["LearningEventInput"];

/**
 * Mutating study calls go straight from the browser to the API rather than
 * through a SvelteKit endpoint: the extra hop would sit inside every
 * interaction the 50 ms budget is measured on, and the stream this surface
 * also opens is same-origin anyway. CSRF stays a double-submit — the token
 * cookie is readable by script by design, and the header is what the server
 * compares against the session.
 */
export type StudyRequestContext = {
  csrfToken: string;
  learningPathId: number;
  sessionId: number;
};

const CSRF_HEADER = "x-csrf-token";
const MISSING_BODY = "The study API answered without a body.";

/**
 * A 200 with no body is a contract violation, not a state to render around.
 */
function requireBody<T>(body: T | undefined): T {
  if (body === undefined) {
    throw new Error(MISSING_BODY);
  }
  return body;
}

const REQUESTED_WITH_HEADER = "x-requested-with";

export function studyMutationHeaders(
  csrfToken: string,
): Record<string, string> {
  return {
    [REQUESTED_WITH_HEADER]: "fetch",
    [CSRF_HEADER]: csrfToken,
  };
}

export async function recordPrediction(
  context: StudyRequestContext,
  input: { topic: string; rating: number; requestId: string },
): Promise<void> {
  const client = createApiClient();
  await unwrapApiResponse(
    client.POST("/api/study/predictions", {
      body: {
        learning_path_id: context.learningPathId,
        session_id: context.sessionId,
        topic: input.topic,
        rating: input.rating,
        request_id: input.requestId,
      },
      headers: studyMutationHeaders(context.csrfToken),
    }),
  );
}

/**
 * `keepalive` lets a request outlive the page that started it.
 *
 * Only used on the teardown path: a grade still inside its cancel window when
 * the learner closes the tab would otherwise be dropped by the browser mid
 * unload. Bodies here are far under the 64 KB the option allows.
 */
export type SendOptions = { keepalive?: boolean };

export async function submitAttempt(
  context: StudyRequestContext,
  input: {
    questionId: string;
    answerText: string;
    confidence: number | null;
    selfRating: number;
    phase: StudyAttemptPhase;
    requestId: string;
  },
  options: SendOptions = {},
): Promise<StudyAttempt> {
  const client = createApiClient();
  const result = await unwrapApiResponse(
    client.POST("/api/study/attempts", {
      body: {
        learning_path_id: context.learningPathId,
        session_id: context.sessionId,
        question_id: input.questionId,
        answer_text: input.answerText,
        confidence: input.confidence,
        self_rating: input.selfRating,
        phase: input.phase,
        request_id: input.requestId,
      },
      headers: studyMutationHeaders(context.csrfToken),
      keepalive: options.keepalive,
    }),
    { normalizeDates: false },
  );
  return requireBody(result).attempt;
}

export async function saveReflection(
  context: StudyRequestContext,
  input: { prompt: string; reflectionText: string; requestId: string },
): Promise<void> {
  const client = createApiClient();
  await unwrapApiResponse(
    client.POST("/api/study/reflections", {
      body: {
        learning_path_id: context.learningPathId,
        session_id: context.sessionId,
        prompt: input.prompt,
        reflection_text: input.reflectionText,
        request_id: input.requestId,
      },
      headers: studyMutationHeaders(context.csrfToken),
    }),
  );
}

export async function completeSession(
  context: StudyRequestContext,
): Promise<StudySession> {
  const client = createApiClient();
  const result = await unwrapApiResponse(
    client.POST("/api/study/sessions/{session_id}/complete", {
      params: { path: { session_id: context.sessionId } },
      headers: studyMutationHeaders(context.csrfToken),
    }),
    { normalizeDates: false },
  );
  return requireBody(result).session;
}

export async function loadSessionSummary(
  sessionId: number,
): Promise<StudySessionSummary> {
  const client = createApiClient();
  const result = await unwrapApiResponse(
    client.GET("/api/study/sessions/{session_id}/summary", {
      params: { path: { session_id: sessionId } },
    }),
    { normalizeDates: false },
  );
  return requireBody(result);
}

export async function ingestLearningEvents(
  context: Pick<StudyRequestContext, "csrfToken" | "learningPathId">,
  events: LearningEventInput[],
  options: SendOptions = {},
): Promise<void> {
  const client = createApiClient();
  await unwrapApiResponse(
    client.POST("/api/events/batch", {
      body: {
        learning_path_id: context.learningPathId,
        events,
      },
      headers: studyMutationHeaders(context.csrfToken),
      keepalive: options.keepalive,
    }),
  );
}

/**
 * A rejected submission is not necessarily lost work: the outbox retries the
 * ones that can succeed later and rolls back the ones that never will.
 */
export function isRetryableFailure(error: NormalizedApiError): boolean {
  return error.status === 0 || error.status === 429 || error.status >= 500;
}
