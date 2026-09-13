import { createApiClient, unwrapApiResponse } from "$lib/api/client";
import { studyMutationHeaders, type SendOptions } from "$lib/api/study";
import type { components } from "$lib/api/schema";

export type ReviewSchedule =
  components["schemas"]["ReviewScheduleItemResponse"];

export type ReviewRequestContext = {
  csrfToken: string;
  learningPathId: number;
};

const MISSING_BODY = "The review API answered without a body.";

/**
 * Record a finished review.
 *
 * The rating the learner pressed goes over the wire as `self_rating`; what it
 * is worth and when the topic comes back are the server's to decide. The
 * returned schedule is the server's answer, not a prediction made here — the
 * FSRS parameters exist in exactly one place, and it is not this one.
 */
export async function completeReview(
  context: ReviewRequestContext,
  input: { topic: string; selfRating: number },
  options: SendOptions = {},
): Promise<ReviewSchedule> {
  const client = createApiClient();
  const result = await unwrapApiResponse(
    client.POST("/api/review/complete", {
      body: {
        learning_path_id: context.learningPathId,
        self_rating: input.selfRating,
        topic: input.topic,
      },
      headers: studyMutationHeaders(context.csrfToken),
      keepalive: options.keepalive,
    }),
    { normalizeDates: false },
  );
  if (result === undefined) {
    throw new Error(MISSING_BODY);
  }
  return result.schedule;
}
