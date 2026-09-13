import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import {
  panelFromResponse,
  readCalibrationList,
  unavailablePanel,
  type CalibrationRating,
  type Panel,
} from "$lib/dashboard/panels";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );
  if (learningPathId === null) {
    return {
      learningPathId,
      ratings: unavailablePanel<CalibrationRating[]>([]),
    };
  }

  return { learningPathId, ratings: await loadRatings(event, learningPathId) };
};

/**
 * The ratings, and nothing derived from them.
 *
 * `/api/calibration/blind-spots` returns the same rows the ratings list
 * already carries an `is_blind_spot` flag on. Asking twice would let the two
 * lists disagree — a topic named as a blind spot that the table below does not
 * show as one — for no information the page does not already have.
 */
async function loadRatings(
  event: Parameters<typeof apiFetch>[0],
  learningPathId: number,
): Promise<Panel<CalibrationRating[]>> {
  try {
    const response = await apiFetch(event, "/api/calibration/ratings", {
      query: { learning_path_id: learningPathId },
    });
    return await panelFromResponse(response, readCalibrationList, []);
  } catch {
    return unavailablePanel([]);
  }
}

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
