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
import { readLearningPaths } from "$lib/learningPath";
import type { PageServerLoad } from "./$types";

type Pacing = components["schemas"]["StudyPacingResponse"];
type ApiEvent = Parameters<typeof apiFetch>[0];

/**
 * The API's widest look-ahead. No interval is longer: FSRS stability is capped
 * at 365 days, so this always reaches the next review there is.
 */
const NEXT_REVIEW_HORIZON_DAYS = 365;

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

/**
 * Every course's reviews, never just the selected one's.
 *
 * The course selection scopes study, topics and content only (#131): with
 * several courses, a review due in one that was not selected would otherwise
 * never be seen. No learning path is sent, so none has to be selected either.
 */
export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const [due, nextReview, courses, pacing] = await Promise.all([
    loadDueReviews(event),
    loadNextReview(event),
    loadCourseLabels(event),
    loadPacing(event),
  ]);

  return {
    courses,
    csrfToken: event.locals.csrfToken,
    due,
    nextReview,
    pacing,
    uiLocale: event.locals.locale,
  };
};

async function loadDueReviews(event: ApiEvent): Promise<Panel<ReviewItem[]>> {
  try {
    const response = await apiFetch(event, "/api/review/due");
    return await panelFromResponse(response, readReviewList, []);
  } catch {
    return unavailablePanel([]);
  }
}

/**
 * The soonest review that is scheduled but not yet due, so an empty page can
 * say when it will next have something — or `null` when nothing is scheduled.
 */
async function loadNextReview(event: ApiEvent): Promise<ReviewItem | null> {
  try {
    const response = await apiFetch(event, "/api/review/upcoming", {
      query: { days_ahead: NEXT_REVIEW_HORIZON_DAYS },
    });
    if (!response.ok) {
      return null;
    }
    const reviews = readReviewList(await response.json());
    return reviews?.find((review) => !review.is_due) ?? null;
  } catch {
    return null;
  }
}

/**
 * Short course titles by learning path id, for labelling each review.
 *
 * Only a label: a TUWEL outage leaves the map empty and the page falls back to
 * the id, rather than hiding reviews the database still holds.
 */
async function loadCourseLabels(
  event: ApiEvent,
): Promise<Record<number, string>> {
  try {
    const response = await apiFetch(event, "/api/learning-paths");
    if (!response.ok) {
      return {};
    }
    const paths = readLearningPaths(await response.json()) ?? [];
    return Object.fromEntries(paths.map((path) => [path.id, path.short_title]));
  } catch {
    return {};
  }
}

/**
 * Reuse the study surface's pacing floors rather than invent review's own.
 *
 * They are served rather than compiled in so that shortening productive
 * friction stays a deployment decision with an audit trail. A second set of
 * numbers for review would be a second place to shorten it.
 */
async function loadPacing(event: ApiEvent): Promise<Pacing> {
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
