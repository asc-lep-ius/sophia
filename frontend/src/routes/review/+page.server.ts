import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import type { components } from "$lib/api/schema";
import {
  panelFromResponse,
  readReviewList,
  unavailablePanel,
  type Panel,
  type ReviewItem,
} from "$lib/dashboard/panels";
import type { PageServerLoad } from "./$types";

type Pacing = components["schemas"]["StudyPacingResponse"];

/**
 * The floors used when the pacing endpoint cannot be reached.
 *
 * Deliberately the stricter reading of "unknown": a review that let the
 * learner reveal instantly because a service was down would quietly turn
 * retrieval practice into re-reading.
 */
const FALLBACK_PACING: Pacing = {
  elaboration_min_chars: 80,
  prompt_min_dwell_ms: 5000,
  reflection_min_seconds: 30,
};

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const learningPathId = Number(event.locals.tenant.learning_path_id);
  if (!Number.isInteger(learningPathId) || learningPathId <= 0) {
    return {
      csrfToken: event.locals.csrfToken,
      due: unavailablePanel<ReviewItem[]>([]),
      learningPathId: null,
      pacing: FALLBACK_PACING,
    };
  }

  const [due, pacing] = await Promise.all([
    loadDueReviews(event, learningPathId),
    loadPacing(event),
  ]);

  return { csrfToken: event.locals.csrfToken, due, learningPathId, pacing };
};

async function loadDueReviews(
  event: Parameters<typeof apiFetch>[0],
  learningPathId: number,
): Promise<Panel<ReviewItem[]>> {
  try {
    const response = await apiFetch(event, "/api/review/due", {
      query: { learning_path_id: learningPathId },
    });
    return await panelFromResponse(response, readReviewList, []);
  } catch {
    return unavailablePanel([]);
  }
}

/**
 * Reuse the study surface's pacing floors rather than invent review's own.
 *
 * They are served rather than compiled in so that shortening productive
 * friction stays a deployment decision with an audit trail. A second set of
 * numbers for review would be a second place to shorten it.
 */
async function loadPacing(
  event: Parameters<typeof apiFetch>[0],
): Promise<Pacing> {
  try {
    const response = await apiFetch(event, "/api/study/pacing");
    if (!response.ok) {
      return FALLBACK_PACING;
    }
    const body: unknown = await response.json();
    return isPacing(body) ? body : FALLBACK_PACING;
  } catch {
    return FALLBACK_PACING;
  }
}

function isPacing(value: unknown): value is Pacing {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as Pacing).elaboration_min_chars === "number" &&
    typeof (value as Pacing).prompt_min_dwell_ms === "number" &&
    typeof (value as Pacing).reflection_min_seconds === "number"
  );
}
