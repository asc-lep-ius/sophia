import { describe, expect, it } from "vitest";

import {
  barRow,
  ratioPercent,
  splitCalibrationRows,
  type CalibrationRow,
  type FigureDatum,
} from "../../src/lib/dashboard/figures";
import { reviewPressure } from "../../src/lib/dashboard/reviewPressure";
import type { ReviewItem } from "../../src/lib/dashboard/panels";

const datum = (key: string, value: number): FigureDatum => ({
  display: String(value),
  key,
  label: key,
  value,
});

describe("dashboard figure geometry", () => {
  it("scales bars against the largest value in the row", () => {
    const bars = barRow([datum("a", 2), datum("b", 8), datum("c", 4)]);

    expect(bars.map((bar) => bar.percent)).toEqual([25, 100, 50]);
  });

  it("draws nothing for a row with no values rather than dividing by zero", () => {
    const bars = barRow([datum("a", 0), datum("b", 0)]);

    expect(bars.map((bar) => bar.percent)).toEqual([0, 0]);
  });

  it("is a pure function of its input, so a server render matches a client one", () => {
    const input = [datum("a", 3), datum("b", 9)];

    expect(barRow(input)).toEqual(barRow(input));
  });

  it("clamps a ratio into the figure's width", () => {
    expect(ratioPercent(0.42)).toBeCloseTo(42);
    expect(ratioPercent(-1)).toBe(0);
    expect(ratioPercent(2)).toBe(100);
  });
});

describe("calibration row split", () => {
  const row = (
    topic: string,
    actual: number | null,
    legacyScored = false,
  ): CalibrationRow => ({ actual, legacyScored, predicted: 0.9, topic });

  it("keeps retired-scorer rows out of the figure and counts them separately", () => {
    const split = splitCalibrationRows([
      row("Graphs", 0.4),
      row("Sorting", 1, true),
      row("Hashing", null),
    ]);

    expect(split.measured.map((entry) => entry.topic)).toEqual(["Graphs"]);
    expect(split.legacyScored.map((entry) => entry.topic)).toEqual(["Sorting"]);
    expect(split.unmeasured.map((entry) => entry.topic)).toEqual(["Hashing"]);
  });

  it("treats a retired-scorer row as excluded even when it has no measurement", () => {
    const split = splitCalibrationRows([row("Graphs", null, true)]);

    expect(split.measured).toEqual([]);
    expect(split.unmeasured).toEqual([]);
    expect(split.legacyScored).toHaveLength(1);
  });
});

describe("review pressure buckets", () => {
  const now = new Date(2026, 8, 12, 9, 30);

  const review = (nextReviewAt: string): ReviewItem => ({
    difficulty: 0.3,
    interval_days: 1,
    interval_index: 0,
    is_due: false,
    last_reviewed_at: null,
    learning_path_id: 12,
    next_review_at: nextReviewAt,
    review_count: 0,
    score_at_last_review: null,
    stability: 1,
    topic: nextReviewAt,
  });

  it("buckets reviews by whole days from the given now", () => {
    const buckets = reviewPressure(
      [
        review(new Date(2026, 8, 12, 23, 0).toISOString()),
        review(new Date(2026, 8, 13, 1, 0).toISOString()),
        review(new Date(2026, 8, 13, 20, 0).toISOString()),
      ],
      { days: 3, now },
    );

    expect(buckets).toEqual([
      { count: 1, dayOffset: 0 },
      { count: 2, dayOffset: 1 },
      { count: 0, dayOffset: 2 },
    ]);
  });

  it("counts an overdue review against today, because today is when it is owed", () => {
    const buckets = reviewPressure(
      [review(new Date(2026, 8, 1, 12, 0).toISOString())],
      { days: 2, now },
    );

    expect(buckets[0]).toEqual({ count: 1, dayOffset: 0 });
  });

  it("drops a review whose due date the API could not express", () => {
    const buckets = reviewPressure([review("not-a-date")], { days: 2, now });

    expect(buckets.every((bucket) => bucket.count === 0)).toBe(true);
  });

  it("ignores reviews past the window rather than piling them on the last day", () => {
    const buckets = reviewPressure(
      [review(new Date(2026, 8, 30, 12, 0).toISOString())],
      { days: 3, now },
    );

    expect(buckets.every((bucket) => bucket.count === 0)).toBe(true);
  });
});
