import type { components } from "$lib/api/schema";

export type SearchResult = components["schemas"]["ContentSearchResultResponse"];
export type SearchSourceFilter =
  components["schemas"]["ContentSearchSourceFilter"];

export const SEARCH_SOURCE_FILTERS = [
  "all",
  "transcript",
  "document",
] as const satisfies readonly SearchSourceFilter[];

export const QUERY_PARAM = "q";
export const SOURCE_PARAM = "source";
export const SOURCE_FILTER_PARAM = "kind";

/** What `/api/search` will accept, so a doomed request is never sent. */
export const MAX_RESULTS = 5;

const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;

const SCORE_STRONG = 0.7;
const SCORE_MODERATE = 0.4;

export type ScoreBand = "strong" | "moderate" | "weak";

/** `MM:SS`, or `H:MM:SS` once an hour is in play — the legacy page's format. */
export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.trunc(seconds));
  const hours = Math.floor(total / SECONDS_PER_HOUR);
  const minutes = Math.floor((total % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const remainder = total % SECONDS_PER_MINUTE;
  const paddedSeconds = String(remainder).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${paddedSeconds}`;
  }
  return `${String(minutes).padStart(2, "0")}:${paddedSeconds}`;
}

/**
 * A relevance band, never a bare percentage.
 *
 * The number an embedding index returns is a distance, not a probability that
 * the passage answers the question. Three bands with words on them say what it
 * is worth; "83%" invites the learner to read a precision that is not there.
 */
export function scoreBand(score: number): ScoreBand {
  if (score >= SCORE_STRONG) {
    return "strong";
  }
  return score >= SCORE_MODERATE ? "moderate" : "weak";
}

export function readSourceFilter(value: string | null): SearchSourceFilter {
  return SEARCH_SOURCE_FILTERS.find((filter) => filter === value) ?? "all";
}

export function readSearchResults(body: unknown): SearchResult[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const results = (body as Record<string, unknown>).results;
  if (!Array.isArray(results)) {
    return null;
  }
  return results.every(isResult) ? (results as SearchResult[]) : null;
}

function isResult(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as SearchResult).content_item_id === "string" &&
    typeof (value as SearchResult).title === "string" &&
    typeof (value as SearchResult).chunk_text === "string" &&
    typeof (value as SearchResult).score === "number"
  );
}
