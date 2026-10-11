import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import { selectedLearningPathId } from "$lib/learningPath";
import { loadCourseLabels } from "$lib/server/courseLabels";
import {
  panelFromResponse,
  readCalibrationList,
  readReviewList,
  readSessionList,
  unavailablePanel,
  type CalibrationRating,
  type Panel,
  type ReviewItem,
  type StudySessionItem,
} from "$lib/dashboard/panels";
import { PRESSURE_DAYS, reviewPressure } from "$lib/dashboard/reviewPressure";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  // Straight from the session tenant, never from a query parameter: a
  // dashboard filter that could name a learning path would be a way to read
  // another one. The API refuses out-of-scope ids as well, and the surface
  // never gives anyone the chance to try.
  const learningPathId = selectedLearningPathId(event.locals.tenant);

  // Review is not scoped by the course selection (#131, #161): a review due in
  // a course that is not selected must still be seen, and before any course
  // has been picked, so those two panels never send a learning path. One
  // failed panel must not take the page with it: each resolves to its own
  // status.
  const [due, upcoming, calibration, sessions] = await Promise.all([
    loadDueReviews(event),
    loadUpcomingReviews(event),
    learningPathId === null
      ? unavailablePanel<CalibrationRating[]>([])
      : loadCalibration(event, learningPathId),
    learningPathId === null
      ? unavailablePanel<StudySessionItem[]>([])
      : loadSessions(event, learningPathId),
  ]);

  // Labels come from TUWEL, which the dashboard otherwise never contacts, so
  // they are fetched only when a due row will show one.
  const courses = due.data.some((review) => review.is_due)
    ? await loadCourseLabels(event)
    : {};

  return {
    calibration,
    courses,
    due,
    learningPathId,
    // Bucketed here rather than in the component: the figure has to render the
    // same on the server and after hydration, and two clocks a few hundred
    // milliseconds apart can straddle midnight.
    pressure: reviewPressure(upcoming.data, {
      days: PRESSURE_DAYS,
      now: new Date(),
    }),
    sessions,
    upcoming,
  };
};

async function loadDueReviews(event: ApiEvent): Promise<Panel<ReviewItem[]>> {
  return panel(() => apiFetch(event, "/api/review/due"), readReviewList, []);
}

async function loadUpcomingReviews(
  event: ApiEvent,
): Promise<Panel<ReviewItem[]>> {
  return panel(
    () =>
      apiFetch(event, "/api/review/upcoming", {
        query: { days_ahead: PRESSURE_DAYS },
      }),
    readReviewList,
    [],
  );
}

/**
 * The whole rating set, not just the blind spots.
 *
 * The split between measured, retired-scorer and not-yet-measured rows is what
 * makes the widget honest, and the blind-spot endpoint has already thrown two
 * of those three away.
 */
async function loadCalibration(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<CalibrationRating[]>> {
  return panel(
    () =>
      apiFetch(event, "/api/calibration/ratings", {
        query: { learning_path_id: learningPathId },
      }),
    readCalibrationList,
    [],
  );
}

/**
 * Sessions, for what is unfinished — never for an outcome figure.
 *
 * The list carries `pre_test_score`, `post_test_score` and `improvement`, and
 * unlike a calibration rating it carries no `legacy_scored` flag, so there is
 * no way to tell a measured session from one the retired scorer touched. #99
 * asks for known-bad rows to be excluded or flagged; with nothing to flag them
 * by, the panel shows what a session *is* rather than what it scored. Widening
 * the list response is what a later phase would need to change first.
 */
async function loadSessions(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<StudySessionItem[]>> {
  return panel(
    () =>
      apiFetch(event, "/api/study/sessions", {
        query: { learning_path_id: learningPathId },
      }),
    readSessionList,
    [],
  );
}

async function panel<T>(
  request: () => Promise<Response>,
  read: (body: unknown) => T | null,
  empty: T,
): Promise<Panel<T>> {
  try {
    return await panelFromResponse(await request(), read, empty);
  } catch {
    return unavailablePanel(empty);
  }
}
