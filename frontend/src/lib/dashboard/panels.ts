import type { components } from "$lib/api/schema";

export type ReviewItem = components["schemas"]["ReviewScheduleItemResponse"];
export type CalibrationRating =
  components["schemas"]["CalibrationRatingResponse"];
export type StudySessionItem =
  components["schemas"]["StudySessionItemResponse"];

/**
 * What a dashboard panel knows about itself.
 *
 * An operations view has to be able to say "this part is missing" without the
 * whole page failing: one API being down is a panel that says so, not a 500.
 * `unauthorized` is kept apart from `error` because they mean different things
 * to the learner — one is a scope they do not have, the other is a service
 * that did not answer.
 */
export type PanelStatus = "ready" | "unauthorized" | "error";

export type Panel<T> = {
  status: PanelStatus;
  data: T;
};

export function readyPanel<T>(data: T): Panel<T> {
  return { status: "ready", data };
}

export function unavailablePanel<T>(empty: T): Panel<T> {
  return { status: "error", data: empty };
}

/**
 * Turn one API response into a panel.
 *
 * `read` is expected to validate: a body that does not match the contract is
 * an error panel rather than a page that renders `undefined`.
 */
export async function panelFromResponse<T>(
  response: Response,
  read: (body: unknown) => T | null,
  empty: T,
): Promise<Panel<T>> {
  if (response.status === 401 || response.status === 403) {
    return { status: "unauthorized", data: empty };
  }
  if (!response.ok) {
    return { status: "error", data: empty };
  }

  try {
    const parsed = read(await response.json());
    return parsed === null
      ? { status: "error", data: empty }
      : { status: "ready", data: parsed };
  } catch {
    return { status: "error", data: empty };
  }
}

export function readReviewList(body: unknown): ReviewItem[] | null {
  const reviews = arrayField(body, "reviews");
  return reviews?.every(isReviewItem) ? (reviews as ReviewItem[]) : null;
}

export function readCalibrationList(body: unknown): CalibrationRating[] | null {
  const ratings = arrayField(body, "ratings");
  return ratings?.every(isCalibrationRating)
    ? (ratings as CalibrationRating[])
    : null;
}

export function readSessionList(body: unknown): StudySessionItem[] | null {
  const sessions = arrayField(body, "sessions");
  return sessions?.every(isSessionItem)
    ? (sessions as StudySessionItem[])
    : null;
}

function arrayField(body: unknown, field: string): unknown[] | null {
  if (!isRecord(body)) {
    return null;
  }
  const value = body[field];
  return Array.isArray(value) ? value : null;
}

function isReviewItem(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.topic === "string" &&
    typeof value.next_review_at === "string" &&
    typeof value.is_due === "boolean" &&
    typeof value.interval_days === "number"
  );
}

function isCalibrationRating(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.topic === "string" &&
    typeof value.predicted === "number" &&
    (value.actual === null || typeof value.actual === "number") &&
    typeof value.legacy_scored === "boolean"
  );
}

function isSessionItem(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.topic === "string" &&
    (value.completed_at === null || typeof value.completed_at === "string")
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}
