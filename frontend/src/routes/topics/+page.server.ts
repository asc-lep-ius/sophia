import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import { selectedLearningPathId } from "$lib/learningPath";
import { unavailablePanel, type Panel } from "$lib/dashboard/panels";
import {
  filterTopicRows,
  readDrawerOpen,
  readTopicFilters,
  type TopicRow,
} from "$lib/content/filters";
import { loadTopicRows } from "$lib/server/topics";
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
  const learningPathId = selectedLearningPathId(event.locals.tenant);

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
  const [rows, contentLanguage] = await Promise.all([
    loadTopicRows(event, learningPathId),
    loadContentLanguage(event, learningPathId, override),
  ]);

  return {
    contentLanguage,
    rows: { data: filterTopicRows(rows.data, filters), status: rows.status },
    totalCount: rows.data.length,
  };
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
