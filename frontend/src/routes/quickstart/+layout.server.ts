import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import type { components } from "$lib/api/schema";
import type { PanelStatus } from "$lib/dashboard/panels";
import type { LayoutServerLoad } from "./$types";

type QuickstartTopic = components["schemas"]["QuickstartTopicResponse"];

export const load: LayoutServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  // No `learning_path_id` query: the API resolves the session's own effective
  // learning path. A wizard that accepted one in the URL would be a way to
  // read another learner's topics.
  let response: Response;
  try {
    response = await apiFetch(event, "/api/quickstart/overview");
  } catch {
    return emptyOverview("error");
  }

  // The API answers 404 when the account has no learning path at all. That is
  // the state a first-run wizard exists for, not a failure.
  if (response.status === 404) {
    return emptyOverview("ready");
  }
  if (response.status === 401 || response.status === 403) {
    return emptyOverview("unauthorized");
  }
  if (!response.ok) {
    return emptyOverview("error");
  }

  try {
    const body: unknown = await response.json();
    return {
      learningPathId: readLearningPathId(body),
      status: "ready" as PanelStatus,
      topics: readTopics(body),
    };
  } catch {
    return emptyOverview("error");
  }
};

function emptyOverview(status: PanelStatus): {
  learningPathId: number | null;
  status: PanelStatus;
  topics: QuickstartTopic[];
} {
  return { learningPathId: null, status, topics: [] };
}

function readLearningPathId(body: unknown): number | null {
  if (!isRecord(body)) {
    return null;
  }
  const value = body.learning_path_id;
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : null;
}

function readTopics(body: unknown): QuickstartTopic[] {
  if (!isRecord(body) || !Array.isArray(body.topics)) {
    return [];
  }
  return body.topics.filter(isTopic);
}

function isTopic(value: unknown): value is QuickstartTopic {
  return isRecord(value) && typeof value.topic === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}
