/** Topics a learner typed, one per line. */
export function parseTopicLines(raw: string): string[] {
  const seen = new Set<string>();
  const topics: string[] = [];
  for (const line of raw.split(/\r?\n/)) {
    const topic = line.trim();
    // Case-insensitive: "graphs" and "Graphs" are one topic to a learner, and
    // saving both would ask them to rate the same thing twice on the next step.
    const key = topic.toLowerCase();
    if (topic && !seen.has(key)) {
      seen.add(key);
      topics.push(topic);
    }
  }
  return topics;
}

export const CONFIDENCE_RATINGS = [1, 2, 3, 4, 5] as const;
export type ConfidenceRating = (typeof CONFIDENCE_RATINGS)[number];

/**
 * Read one confidence rating per topic out of a submitted form.
 *
 * Topics without a rating are left out rather than defaulted: a prediction
 * nobody made is not a prediction, and inventing a middle value would put a
 * number the learner never committed to into the calibration comparison.
 */
export function readConfidenceRatings(
  form: Iterable<[string, FormDataEntryValue]>,
  topics: string[],
): Record<string, number> {
  const allowed = new Set(topics);
  const ratings: Record<string, number> = {};
  for (const [name, value] of form) {
    const topic = name.startsWith("rating:")
      ? name.slice("rating:".length)
      : null;
    if (topic === null || !allowed.has(topic)) {
      continue;
    }
    const rating = Number(value);
    if (CONFIDENCE_RATINGS.includes(rating as ConfidenceRating)) {
      ratings[topic] = rating;
    }
  }
  return ratings;
}
