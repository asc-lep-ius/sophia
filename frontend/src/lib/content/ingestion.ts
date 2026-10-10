import type { components } from "$lib/api/schema";
import type { ContentItem } from "$lib/content/filters";

export type IngestionStatus = components["schemas"]["IngestionStatusResponse"];
export type IngestionJob = components["schemas"]["IngestionJobResponse"];
export type IngestionSettings =
  components["schemas"]["IngestionSettingsResponse"];

/** The languages a learner can pin a course's transcription to; "" is detection. */
export const TRANSCRIPTION_LANGUAGES = ["", "de", "en"] as const;

/** One of the learning path's sources with the state of each of its items. */
export type IngestionSourceStatus = {
  id: number;
  title: string;
  items: ContentItem[];
};

/**
 * The outcomes Process and "Process older recordings too" can have, as the
 * actions report them.
 *
 * `already_running`, `nothing_older` and `unavailable` are refusals the API
 * makes on purpose and the page has to say; `failed` is everything else.
 * `started_older` is the second button's success, worded as a one-off.
 */
export type ProcessOutcome =
  | "started"
  | "started_older"
  | "already_running"
  | "nothing_older"
  | "unavailable";

/** The status body, or `null` when it is not the contract. */
export function readIngestionStatus(body: unknown): IngestionStatus | null {
  if (!isRecord(body)) {
    return null;
  }
  const settings = body.settings;
  const worker = body.worker;
  if (
    typeof body.learning_path_id !== "number" ||
    !isRecord(settings) ||
    typeof settings.subscribed !== "boolean" ||
    !isRecord(worker) ||
    typeof worker.available !== "boolean" ||
    typeof worker.reason !== "string" ||
    !Array.isArray(body.sources) ||
    typeof body.older_recordings_pending !== "number" ||
    (body.job !== null && !isJob(body.job))
  ) {
    return null;
  }
  return body as IngestionStatus;
}

/** The error code a refusal carried, read from the API's error envelope. */
export function readRefusalCode(body: unknown): string {
  if (!isRecord(body) || !isRecord(body.detail)) {
    return "";
  }
  return typeof body.detail.code === "string" ? body.detail.code : "";
}

/** The reason a refusal carried, read from the API's error envelope. */
export function readRefusalReason(body: unknown): string {
  if (
    !isRecord(body) ||
    !isRecord(body.detail) ||
    !isRecord(body.detail.params)
  ) {
    return "";
  }
  const reason = body.detail.params.reason;
  return typeof reason === "string" ? reason : "";
}

/** Whether the job is one the page should keep asking about. */
export function isJobActive(job: IngestionJob | null): boolean {
  return job !== null && (job.state === "queued" || job.state === "processing");
}

/**
 * Processing counts as done for an item once its transcript is indexed and its
 * topics are extracted. A failure at any stage is reported as such, with the
 * reason the API attached, so the learner can retry rather than wonder.
 */
export type ItemOutcome = "ready" | "failed" | "processing" | "pending";

export function itemOutcome(item: ContentItem): ItemOutcome {
  const stages = [
    item.download_status,
    item.transcription_status,
    item.index_status,
    item.topic_status,
  ];
  if (stages.includes("failed")) {
    return "failed";
  }
  if (item.topic_status === "completed") {
    return "ready";
  }
  if (
    stages.some((stage) => stage === "processing" || stage === "downloading")
  ) {
    return "processing";
  }
  return "pending";
}

function isJob(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.state === "string" &&
    (value.error === null || typeof value.error === "string")
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
