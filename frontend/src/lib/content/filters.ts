import type { components } from "$lib/api/schema";

export type ContentItem = components["schemas"]["ContentItemResponse"];
export type ContentSource = components["schemas"]["ContentSourceResponse"];
export type TopicMapping = components["schemas"]["TopicMappingResponse"];
export type TopicConfidence =
  components["schemas"]["TopicConfidenceRatingResponse"];

export const CONTENT_STATUSES = ["all", "pending", "ready"] as const;
export type ContentStatus = (typeof CONTENT_STATUSES)[number];

export const TOPIC_ORIGINS = ["all", "transcript", "quiz", "manual"] as const;
export type TopicOriginFilter = (typeof TOPIC_ORIGINS)[number];

export const TOPIC_RATINGS = ["all", "rated", "unrated"] as const;
export type TopicRatingFilter = (typeof TOPIC_RATINGS)[number];

export const QUERY_PARAM = "q";
export const STATUS_PARAM = "status";
export const ORIGIN_PARAM = "origin";
export const RATED_PARAM = "rated";
export const DRAWER_PARAM = "filters";

export type ContentFilters = {
  query: string;
  status: ContentStatus;
};

export type TopicFilters = {
  origin: TopicOriginFilter;
  query: string;
  rated: TopicRatingFilter;
};

export type ContentGroup = {
  itemCount: number;
  items: ContentItem[];
  readyCount: number;
  source: ContentSource;
};

export type TopicRow = {
  confidence: TopicConfidence | null;
  topic: TopicMapping;
};

/**
 * Filters live in the URL, never in a store.
 *
 * Reload, back button and a shared link all have to land on the same list, and
 * a filter the server cannot see is one the server cannot apply — which would
 * leave the first paint showing rows the learner already filtered away.
 */
export function readContentFilters(url: URL): ContentFilters {
  return {
    query: readQuery(url),
    status: readOption(url, STATUS_PARAM, CONTENT_STATUSES),
  };
}

export function readTopicFilters(url: URL): TopicFilters {
  return {
    origin: readOption(url, ORIGIN_PARAM, TOPIC_ORIGINS),
    query: readQuery(url),
    rated: readOption(url, RATED_PARAM, TOPIC_RATINGS),
  };
}

/** Whether the mobile filter drawer was opened, which is also a URL fact. */
export function readDrawerOpen(url: URL): boolean {
  return url.searchParams.get(DRAWER_PARAM) === "open";
}

export function isContentItemReady(item: ContentItem): boolean {
  return (
    item.download_status === "completed" &&
    item.transcription_status === "completed" &&
    item.index_status === "completed"
  );
}

export function groupContent(
  sources: ContentSource[],
  itemsBySource: Map<number, ContentItem[]>,
  filters: ContentFilters,
): ContentGroup[] {
  const groups: ContentGroup[] = [];
  for (const source of sources) {
    const items = itemsBySource.get(source.id) ?? [];
    const matching = items.filter((item) =>
      matchesContentFilters(item, filters),
    );
    if (matching.length === 0) {
      continue;
    }
    groups.push({
      itemCount: items.length,
      items: matching,
      readyCount: matching.filter(isContentItemReady).length,
      source,
    });
  }
  return groups;
}

export function filterTopicRows(
  rows: TopicRow[],
  filters: TopicFilters,
): TopicRow[] {
  return rows.filter((row) => matchesTopicFilters(row, filters));
}

/**
 * Pair each topic with its rating, keeping topics nothing has rated yet.
 *
 * An inner join would hide exactly the topics worth studying: the ones the
 * learner has never committed a prediction to.
 */
export function topicRows(
  topics: TopicMapping[],
  ratings: TopicConfidence[],
): TopicRow[] {
  const byTopic = new Map(ratings.map((rating) => [rating.topic, rating]));
  return topics.map((topic) => ({
    confidence: byTopic.get(topic.topic) ?? null,
    topic,
  }));
}

function matchesContentFilters(
  item: ContentItem,
  filters: ContentFilters,
): boolean {
  if (filters.status === "ready" && !isContentItemReady(item)) {
    return false;
  }
  if (filters.status === "pending" && isContentItemReady(item)) {
    return false;
  }
  return matchesQuery(item.title, filters.query);
}

function matchesTopicFilters(row: TopicRow, filters: TopicFilters): boolean {
  if (filters.origin !== "all" && row.topic.source !== filters.origin) {
    return false;
  }
  if (filters.rated === "rated" && row.confidence === null) {
    return false;
  }
  if (filters.rated === "unrated" && row.confidence !== null) {
    return false;
  }
  return matchesQuery(row.topic.topic, filters.query);
}

function matchesQuery(haystack: string, query: string): boolean {
  return query === "" || haystack.toLowerCase().includes(query.toLowerCase());
}

function readQuery(url: URL): string {
  return (url.searchParams.get(QUERY_PARAM) ?? "").trim();
}

function readOption<T extends string>(
  url: URL,
  name: string,
  allowed: readonly [T, ...T[]],
): T {
  const value = url.searchParams.get(name) ?? "";
  // Anything unrecognised falls back to the first option rather than erroring:
  // a hand-edited or stale query string should still render a list.
  return (allowed as readonly string[]).includes(value)
    ? (value as T)
    : allowed[0];
}

/**
 * The filter state a navigation has to carry, as form fields.
 *
 * Links here are GET forms rather than hand-built query strings: the browser
 * assembles the URL, so the filters stay addressable without any code
 * concatenating one, and every one of them still works before hydration.
 * Defaults are left out so a plain list keeps a clean URL.
 */
export function contentParams(
  filters: ContentFilters,
  language: string | null,
): Record<string, string> {
  return carried({
    lang: language,
    [QUERY_PARAM]: filters.query,
    [STATUS_PARAM]: filters.status === "all" ? "" : filters.status,
  });
}

export function topicParams(
  filters: TopicFilters,
  language: string | null,
): Record<string, string> {
  return carried({
    lang: language,
    [ORIGIN_PARAM]: filters.origin === "all" ? "" : filters.origin,
    [QUERY_PARAM]: filters.query,
    [RATED_PARAM]: filters.rated === "all" ? "" : filters.rated,
  });
}

function carried(
  values: Record<string, string | null>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values).filter(
      (entry): entry is [string, string] =>
        entry[1] !== null && entry[1] !== "",
    ),
  );
}
