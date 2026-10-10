import { apiFetch } from "../../hooks.server";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import {
  topicRows,
  type TopicConfidence,
  type TopicMapping,
  type TopicRow,
} from "$lib/content/filters";

type ApiEvent = Parameters<typeof apiFetch>[0];

/**
 * A learning path's topics, each paired with its latest rating.
 *
 * Shared by the topic list and the study picker, so the topic a learner sees
 * on one page is the same string the other starts a session on.
 */
export async function loadTopicRows(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<TopicRow[]>> {
  const [topics, ratings] = await Promise.all([
    loadTopics(event, learningPathId),
    loadRatings(event, learningPathId),
  ]);
  // The panel's status comes from the topic list: a missing confidence list
  // means nothing is rated yet, which is a legitimate state, not a failure.
  return { data: topicRows(topics.data, ratings.data), status: topics.status };
}

async function loadTopics(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<TopicMapping[]>> {
  try {
    const response = await apiFetch(
      event,
      "/api/learning-paths/{learning_path_id}/topics",
      { params: { learning_path_id: learningPathId } },
    );
    return await panelFromResponse(response, readTopicList, []);
  } catch {
    return unavailablePanel([]);
  }
}

async function loadRatings(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<TopicConfidence[]>> {
  try {
    const response = await apiFetch(
      event,
      "/api/learning-paths/{learning_path_id}/topics/confidence",
      { params: { learning_path_id: learningPathId } },
    );
    return await panelFromResponse(response, readRatingList, []);
  } catch {
    return unavailablePanel([]);
  }
}

function readTopicList(body: unknown): TopicMapping[] | null {
  const topics = arrayField(body, "topics");
  return topics?.every(isTopic) ? (topics as TopicMapping[]) : null;
}

function readRatingList(body: unknown): TopicConfidence[] | null {
  const ratings = arrayField(body, "ratings");
  return ratings?.every(isRating) ? (ratings as TopicConfidence[]) : null;
}

function arrayField(body: unknown, field: string): unknown[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const value = (body as Record<string, unknown>)[field];
  return Array.isArray(value) ? value : null;
}

function isTopic(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as TopicMapping).topic === "string" &&
    typeof (value as TopicMapping).source === "string" &&
    typeof (value as TopicMapping).frequency === "number"
  );
}

function isRating(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as TopicConfidence).topic === "string" &&
    typeof (value as TopicConfidence).predicted === "number"
  );
}
