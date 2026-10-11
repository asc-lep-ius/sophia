import type { components } from "$lib/api/schema";

export type CardConfidenceTopic =
  components["schemas"]["CardConfidenceTopicResponse"];

/**
 * The learner's answers that carried a confidence, per topic, and how many
 * did not: those were given before cards asked, and are counted apart rather
 * than read as unsure.
 */
export type CardConfidence = {
  topics: CardConfidenceTopic[];
  unrated: number;
};

export const NO_CARD_CONFIDENCE: CardConfidence = { topics: [], unrated: 0 };

export function readCardConfidence(body: unknown): CardConfidence | null {
  if (
    !isRecord(body) ||
    typeof body.unrated !== "number" ||
    !Array.isArray(body.topics) ||
    !body.topics.every(isTopic)
  ) {
    return null;
  }
  return {
    topics: body.topics as CardConfidenceTopic[],
    unrated: body.unrated,
  };
}

function isTopic(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.topic === "string" &&
    typeof value.rated === "number" &&
    typeof value.sure === "number" &&
    typeof value.sure_again === "number"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
