import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import { selectedLearningPathId } from "$lib/learningPath";
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
import {
  PRESSURE_DAYS,
  reviewPressure,
  type PressureBucket,
} from "$lib/dashboard/reviewPressure";
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
  if (learningPathId === null) {
    return {
      calibration: unavailablePanel<CalibrationRating[]>([]),
      due: unavailablePanel<ReviewItem[]>([]),
      learningPathId: null,
      pressure: [] as PressureBucket[],
      sessions: unavailablePanel<StudySessionItem[]>([]),
      upcoming: unavailablePanel<ReviewItem[]>([]),
    };
  }

  // One slow panel must not hold up the other three, and one failed panel must
  // not take the page with it: each resolves to its own status.
  const [due, upcoming, calibration, sessions] = await Promise.all([
    loadDueReviews(event, learningPathId),
    loadUpcomingReviews(event, learningPathId),
    loadCalibration(event, learningPathId),
    loadSessions(event, learningPathId),
  ]);

  return {
    calibration,
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

async function loadDueReviews(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<ReviewItem[]>> {
  return panel(
    () =>
      apiFetch(event, "/api/review/due", {
        query: { learning_path_id: learningPathId },
      }),
    readReviewList,
    [],
  );
}

async function loadUpcomingReviews(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<ReviewItem[]>> {
  return panel(
    () =>
      apiFetch(event, "/api/review/upcoming", {
        query: { days_ahead: PRESSURE_DAYS, learning_path_id: learningPathId },
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
