import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import {
  filterTopicRows,
  readDrawerOpen,
  readTopicFilters,
  topicRows,
  type TopicConfidence,
  type TopicMapping,
  type TopicRow,
} from "$lib/content/filters";
import {
  fallbackContentLanguage,
  readContentLanguage,
  readLanguageOverride,
  type ContentLanguageState,
} from "$lib/content/language";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const filters = readTopicFilters(event.url);
  const override = readLanguageOverride(event.url);
  // Straight from the session tenant, never from the query string: a filter
  // that could name a learning path would be a way to read another one.
  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );

  const scoped =
    learningPathId === null
      ? unscopedTopics(override)
      : await loadScopedTopics(event, learningPathId, override, filters);

  return {
    contentLanguage: scoped.contentLanguage,
    drawerOpen: readDrawerOpen(event.url),
    filters,
    learningPathId,
    rows: scoped.rows,
    totalCount: scoped.totalCount,
    uiLocale: event.locals.locale,
  };
};

type ScopedTopics = {
  contentLanguage: ContentLanguageState;
  rows: Panel<TopicRow[]>;
  totalCount: number;
};

function unscopedTopics(
  override: ReturnType<typeof readLanguageOverride>,
): ScopedTopics {
  return {
    contentLanguage: fallbackContentLanguage(override),
    rows: unavailablePanel<TopicRow[]>([]),
    totalCount: 0,
  };
}

async function loadScopedTopics(
  event: ApiEvent,
  learningPathId: number,
  override: ReturnType<typeof readLanguageOverride>,
  filters: ReturnType<typeof readTopicFilters>,
): Promise<ScopedTopics> {
  const [topics, ratings, contentLanguage] = await Promise.all([
    loadTopics(event, learningPathId),
    loadRatings(event, learningPathId),
    loadContentLanguage(event, learningPathId, override),
  ]);

  const rows = topicRows(topics.data, ratings.data);
  return {
    contentLanguage,
    // The panel's status comes from the topic list: a missing confidence list
    // means nothing is rated yet, which is a legitimate state, not a failure.
    rows: { data: filterTopicRows(rows, filters), status: topics.status },
    totalCount: rows.length,
  };
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

async function loadContentLanguage(
  event: ApiEvent,
  learningPathId: number,
  override: ReturnType<typeof readLanguageOverride>,
): Promise<ContentLanguageState> {
  try {
    const response = await apiFetch(
      event,
      "/api/learning-paths/{learning_path_id}/content-language",
      {
        params: { learning_path_id: learningPathId },
        query: { lang: override },
      },
    );
    if (!response.ok) {
      return fallbackContentLanguage(override);
    }
    return (
      readContentLanguage(await response.json(), override) ??
      fallbackContentLanguage(override)
    );
  } catch {
    return fallbackContentLanguage(override);
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

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
