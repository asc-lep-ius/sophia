import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import { selectedLearningPathId } from "$lib/learningPath";
import {
  NO_CARD_CONFIDENCE,
  readCardConfidence,
  type CardConfidence,
} from "$lib/calibration/cardConfidence";
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

  const learningPathId = selectedLearningPathId(event.locals.tenant);
  if (learningPathId === null) {
    return {
      learningPathId,
      ratings: unavailablePanel<CalibrationRating[]>([]),
      cardConfidence: unavailablePanel(NO_CARD_CONFIDENCE),
    };
  }

  const [ratings, cardConfidence] = await Promise.all([
    loadRatings(event, learningPathId),
    loadCardConfidence(event, learningPathId),
  ]);
  return { learningPathId, ratings, cardConfidence };
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

/** Per card rather than per topic: how often a sure answer met Again. */
async function loadCardConfidence(
  event: Parameters<typeof apiFetch>[0],
  learningPathId: number,
): Promise<Panel<CardConfidence>> {
  try {
    const response = await apiFetch(event, "/api/calibration/card-confidence", {
      query: { learning_path_id: learningPathId },
    });
    return await panelFromResponse(
      response,
      readCardConfidence,
      NO_CARD_CONFIDENCE,
    );
  } catch {
    return unavailablePanel(NO_CARD_CONFIDENCE);
  }
}
