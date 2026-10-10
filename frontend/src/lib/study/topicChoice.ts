import type { TopicRow } from "$lib/content/filters";

/**
 * How far a topic's prediction overshot its score; 0 when that is unknown.
 *
 * Only overconfidence counts, as it does for the CLI's blind spots: a topic
 * the learner under-predicted is one they already do better on than they
 * think, so it is no reason to study it first.
 */
export function confidenceGap(row: TopicRow): number {
  return Math.max(row.confidence?.calibration_error ?? 0, 0);
}

/**
 * Topics in the order the study picker offers them: largest gap first.
 *
 * `sophia study session` auto-selects the topic where the gap is largest and
 * falls back to the course's first topic; the head of this list is that same
 * choice. The sort is stable, so topics with no known gap keep the course's
 * own order behind the ones that have one.
 */
export function rankTopicsByGap(rows: TopicRow[]): TopicRow[] {
  return [...rows].sort((a, b) => confidenceGap(b) - confidenceGap(a));
}
