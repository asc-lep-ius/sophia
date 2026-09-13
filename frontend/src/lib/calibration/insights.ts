import {
  splitCalibrationRows,
  type CalibrationRow,
} from "$lib/dashboard/figures";
import type { CalibrationRating } from "$lib/dashboard/panels";

/**
 * How many measured ratings this surface needs before it describes a pattern.
 *
 * Below it the page still shows every row it has; what it withholds is the
 * language that turns rows into a finding. Three is not a statistical
 * threshold and is not offered as one — it is the smallest number at which a
 * pattern is not simply the last thing that happened, and the copy says how
 * many measurements the reading rests on either way.
 */
export const MIN_MEASURED_FOR_READING = 3;

export type BlindSpot = {
  topic: string;
  /** Percentage points by which the prediction overshot the measurement. */
  gapPercent: number;
};

export type CalibrationView = {
  /** Rows a figure may be drawn from: measured, and not by the retired scorer. */
  measured: CalibrationRow[];
  legacyScoredCount: number;
  unmeasuredCount: number;
  /** Topics the *server* flagged, worst overshoot first. */
  blindSpots: BlindSpot[];
  /** Whether there is enough measured data to describe a pattern at all. */
  hasReading: boolean;
};

export function calibrationRow(rating: CalibrationRating): CalibrationRow {
  return {
    actual: rating.actual,
    legacyScored: rating.legacy_scored,
    predicted: rating.predicted,
    topic: rating.topic,
  };
}

/**
 * Everything this surface is allowed to say, derived in one place.
 *
 * Two rules are doing the work. Nothing here decides *whether* a topic is a
 * blind spot — `is_blind_spot` is the server's verdict and the page only sorts
 * and renders it, so the threshold lives in one place rather than drifting
 * between a page and a service. And a row the retired scorer touched (#97)
 * reported an `actual` of 1.0 for anything submitted, so it is not a
 * measurement: including it would not blur the picture, it would manufacture a
 * confident one. Those rows are counted where the learner can see the count
 * and kept out of every figure and every verdict.
 */
export function calibrationView(ratings: CalibrationRating[]): CalibrationView {
  const measurable = ratings.filter((rating) => !rating.legacy_scored);
  const split = splitCalibrationRows(ratings.map(calibrationRow));

  return {
    blindSpots: measurable
      .filter((rating) => rating.is_blind_spot && rating.actual !== null)
      .map((rating) => ({
        gapPercent: Math.round((rating.predicted - (rating.actual ?? 0)) * 100),
        topic: rating.topic,
      }))
      .sort((left, right) => right.gapPercent - left.gapPercent),
    hasReading: split.measured.length >= MIN_MEASURED_FOR_READING,
    legacyScoredCount: split.legacyScored.length,
    measured: split.measured,
    unmeasuredCount: split.unmeasured.length,
  };
}
