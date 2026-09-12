import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import {
  groupContent,
  readContentFilters,
  readDrawerOpen,
  type ContentItem,
  type ContentSource,
} from "$lib/content/filters";
import {
  fallbackContentLanguage,
  readContentLanguage,
  readLanguageOverride,
  type ContentLanguageState,
} from "$lib/content/language";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

/**
 * How many sources get their items fetched.
 *
 * The catalog endpoint lists sources without their items, so the page pays one
 * request per source. A learner has a handful; a cap keeps a misconfigured
 * tenant from turning one page load into hundreds of upstream calls.
 */
const SOURCE_FETCH_LIMIT = 25;

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const filters = readContentFilters(event.url);
  const override = readLanguageOverride(event.url);
  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );

  const [sources, contentLanguage] = await Promise.all([
    loadSources(event),
    loadContentLanguage(event, learningPathId, override),
  ]);

  const itemsBySource = await loadItems(
    event,
    sources.data.slice(0, SOURCE_FETCH_LIMIT),
  );

  return {
    contentLanguage,
    drawerOpen: readDrawerOpen(event.url),
    filters,
    // Filtered here rather than in the component: the URL is the source of
    // truth for the filter, so the first paint has to already agree with it.
    groups: groupContent(sources.data, itemsBySource, filters),
    sourceCount: sources.data.length,
    sources: sources as Panel<ContentSource[]>,
    uiLocale: event.locals.locale,
  };
};

async function loadSources(event: ApiEvent): Promise<Panel<ContentSource[]>> {
  try {
    const response = await apiFetch(event, "/api/content-sources");
    return await panelFromResponse(response, readSourceList, []);
  } catch {
    return unavailablePanel([]);
  }
}

/**
 * Items for every source, in parallel and independently.
 *
 * One source whose items fail to load leaves the rest of the catalog readable:
 * it simply contributes nothing rather than taking the page down.
 */
async function loadItems(
  event: ApiEvent,
  sources: ContentSource[],
): Promise<Map<number, ContentItem[]>> {
  const loaded = await Promise.all(
    sources.map(async (source): Promise<[number, ContentItem[]]> => {
      try {
        const response = await apiFetch(
          event,
          "/api/content-sources/{content_source_id}/content-items",
          { params: { content_source_id: source.id } },
        );
        if (!response.ok) {
          return [source.id, []];
        }
        return [source.id, readItemList(await response.json()) ?? []];
      } catch {
        return [source.id, []];
      }
    }),
  );
  return new Map(loaded);
}

/**
 * Ask the server what language the content is in; never infer it here.
 *
 * `Accept-Language` and the UI locale describe the chrome the learner reads,
 * not the language their exam is written in. Treating either as the source of
 * truth is the misuse this surface is supposed to prevent.
 */
async function loadContentLanguage(
  event: ApiEvent,
  learningPathId: number | null,
  override: ReturnType<typeof readLanguageOverride>,
): Promise<ContentLanguageState> {
  if (learningPathId === null) {
    return fallbackContentLanguage(override);
  }

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

function readSourceList(body: unknown): ContentSource[] | null {
  const sources = arrayField(body, "sources");
  return sources?.every(isSource) ? (sources as ContentSource[]) : null;
}

function readItemList(body: unknown): ContentItem[] | null {
  const items = arrayField(body, "items");
  return items?.every(isItem) ? (items as ContentItem[]) : null;
}

function arrayField(body: unknown, field: string): unknown[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const value = (body as Record<string, unknown>)[field];
  return Array.isArray(value) ? value : null;
}

function isSource(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as ContentSource).id === "number" &&
    typeof (value as ContentSource).title === "string"
  );
}

function isItem(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as ContentItem).id === "string" &&
    typeof (value as ContentItem).title === "string" &&
    typeof (value as ContentItem).download_status === "string"
  );
}

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
