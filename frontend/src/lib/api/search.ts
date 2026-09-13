import { createApiClient, unwrapApiResponse } from "$lib/api/client";
import { studyMutationHeaders } from "$lib/api/study";
import {
  MAX_RESULTS,
  type SearchResult,
  type SearchSourceFilter,
} from "$lib/search/results";

export type SearchRequestContext = {
  csrfToken: string;
  contentSourceId: number;
  learningPathId: number;
};

export type SearchInput = {
  query: string;
  sourceFilter: SearchSourceFilter;
};

const MISSING_BODY = "The search API answered without a body.";

/**
 * Run one content search from the browser.
 *
 * Straight to the API rather than through a SvelteKit endpoint: the page is
 * searching as the learner types, and a second hop would put a server render
 * inside every keystroke's latency. The `signal` is the caller's — the
 * controller aborts a run the moment a newer one is scheduled.
 *
 * The learning path is sent explicitly and the server checks the content
 * source belongs to it. Neither number is a filter the browser is trusted on.
 */
export async function searchContent(
  context: SearchRequestContext,
  input: SearchInput,
  signal?: AbortSignal,
): Promise<SearchResult[]> {
  const client = createApiClient();
  const result = await unwrapApiResponse(
    client.POST("/api/search", {
      body: {
        content_source_id: context.contentSourceId,
        learning_path_id: context.learningPathId,
        // Always the whole source: "only what I missed" was a lecture-specific
        // filter on the legacy page and has no control on this one.
        missed_only: false,
        n_results: MAX_RESULTS,
        query: input.query,
        source_filter: input.sourceFilter,
      },
      headers: studyMutationHeaders(context.csrfToken),
      signal,
    }),
    { normalizeDates: false },
  );
  if (result === undefined) {
    throw new Error(MISSING_BODY);
  }
  return result.results;
}
