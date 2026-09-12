import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import type { ContentSource } from "$lib/content/filters";
import {
  MAX_RESULTS,
  QUERY_PARAM,
  SOURCE_FILTER_PARAM,
  SOURCE_PARAM,
  readSearchResults,
  readSourceFilter,
  type SearchResult,
  type SearchSourceFilter,
} from "$lib/search/results";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );
  const sources = await loadSources(event);
  const selectedSource = selectSource(sources.data, event.url);
  const sourceFilter = readSourceFilter(
    event.url.searchParams.get(SOURCE_FILTER_PARAM),
  );
  const query = (event.url.searchParams.get(QUERY_PARAM) ?? "").trim();

  return {
    csrfToken: event.locals.csrfToken,
    learningPathId,
    query,
    // Searched here as well as in the browser so the page answers a submitted
    // query before it hydrates: a shared `?q=` link and a browser with no
    // JavaScript both land on results rather than on an empty box. The live
    // debounced search is the enhancement on top, not the only way in.
    results: await loadResults(event, {
      contentSourceId: selectedSource?.id ?? null,
      learningPathId,
      query,
      sourceFilter,
    }),
    selectedSourceId: selectedSource?.id ?? null,
    sourceFilter,
    sources,
  };
};

type SearchScope = {
  contentSourceId: number | null;
  learningPathId: number | null;
  query: string;
  sourceFilter: SearchSourceFilter;
};

async function loadResults(
  event: ApiEvent,
  scope: SearchScope,
): Promise<Panel<SearchResult[]> | null> {
  if (
    scope.query === "" ||
    scope.contentSourceId === null ||
    scope.learningPathId === null
  ) {
    // Null rather than an empty panel: "nothing was asked" and "nothing was
    // found" read identically once they are both an empty list.
    return null;
  }

  try {
    const response = await apiFetch(event, "/api/search", {
      body: JSON.stringify({
        content_source_id: scope.contentSourceId,
        learning_path_id: scope.learningPathId,
        missed_only: false,
        n_results: MAX_RESULTS,
        query: scope.query,
        source_filter: scope.sourceFilter,
      }),
      headers: { "content-type": "application/json" },
      method: "POST",
    });
    return await panelFromResponse(response, readSearchResults, []);
  } catch {
    return unavailablePanel([]);
  }
}

async function loadSources(event: ApiEvent): Promise<Panel<ContentSource[]>> {
  try {
    const response = await apiFetch(event, "/api/content-sources");
    return await panelFromResponse(response, readSourceList, []);
  } catch {
    return unavailablePanel([]);
  }
}

/**
 * The source to search, chosen from what the learner actually has.
 *
 * A `?source=` naming something outside the catalogue falls back to the first
 * one rather than travelling to the API: the server checks ownership too, but
 * a page that forwards an arbitrary id is a page that reports another tenant's
 * refusal as its own error state.
 */
function selectSource(
  sources: ContentSource[],
  url: URL,
): ContentSource | null {
  const requested = Number(url.searchParams.get(SOURCE_PARAM));
  const match = sources.find((source) => source.id === requested);
  return match ?? sources[0] ?? null;
}

function readSourceList(body: unknown): ContentSource[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const sources = (body as Record<string, unknown>).sources;
  if (!Array.isArray(sources)) {
    return null;
  }
  return sources.every(
    (source) =>
      source !== null &&
      typeof source === "object" &&
      typeof (source as ContentSource).id === "number" &&
      typeof (source as ContentSource).title === "string",
  )
    ? (sources as ContentSource[])
    : null;
}

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
