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
 * "Largest gap" is the README's description of `sophia study session`, which
 * the CLI itself only approximates (it takes the alphabetically first blind
 * spot). The sort is stable, so topics with no known gap keep the course's own
 * order behind the ones that have one, and the head is then the course's
 * first topic, which is the CLI's fallback too.
 */
export function rankTopicsByGap(rows: TopicRow[]): TopicRow[] {
  return [...rows].sort((a, b) => confidenceGap(b) - confidenceGap(a));
}

/**
 * One row per topic name, keeping the first and so the most frequent.
 *
 * The API lists a topic once per source, so a name the learner typed in
 * quickstart and extraction also found comes back twice. A session is started
 * on the name alone, which makes the two rows one choice.
 */
export function distinctTopics(rows: TopicRow[]): TopicRow[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    if (seen.has(row.topic.topic)) {
      return false;
    }
    seen.add(row.topic.topic);
    return true;
  });
}
