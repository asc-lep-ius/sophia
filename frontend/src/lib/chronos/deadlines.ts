import type { components } from "$lib/api/schema";

export type Deadline = components["schemas"]["DeadlineResponse"];
export type Workload = components["schemas"]["WorkloadResponse"];
export type EffortCalibrationMetric =
  components["schemas"]["EffortCalibrationMetricResponse"];

/**
 * The horizon the legacy deadlines page asked for.
 *
 * `/api/deadlines` defaults to 14; the NiceGUI page passed 30 and a learner
 * planning around it has 30 days of deadlines in front of them. Taking the
 * endpoint's default instead would silently shorten their month.
 */
export const DEADLINE_HORIZON_DAYS = 30;

/**
 * How many past deadlines the history surface asks for.
 *
 * Shorter than the endpoint's default of 50, and than the legacy page's, on
 * purpose: whether a past deadline was reflected on lives behind its own
 * endpoint, so classifying the list costs one request per row. Fifty rows is
 * fifty upstream calls for one page view. Twenty-five is a page of history a
 * learner actually reads, and the count is said out loud so a truncated list
 * cannot be mistaken for the whole record.
 */
export const HISTORY_LIMIT = 25;

const SECONDS_PER_DAY = 86_400;

export const DEADLINE_OUTCOMES = ["all", "on_time", "late", "missed"] as const;
export type OutcomeFilter = (typeof DEADLINE_OUTCOMES)[number];
export type DeadlineOutcome = Exclude<OutcomeFilter, "all">;

export const OUTCOME_PARAM = "outcome";

export type DueUrgency = "overdue" | "today" | "upcoming";

export type DueDistance = {
  /** Whole days between now and the due instant, floored towards the past. */
  days: number;
  urgency: DueUrgency;
};

/**
 * How far away a deadline is, in whole days.
 *
 * Elapsed seconds rather than calendar arithmetic, which is what the legacy
 * service does and the only version that cannot drift: a browser in
 * Europe/Vienna and a server in UTC disagree about which calendar day an
 * instant falls in, and they disagree twice a year by an extra hour. Counting
 * the seconds between two instants is the same number everywhere, so the
 * phrase the learner reads is the server's answer rather than their timezone's.
 *
 * Floored rather than rounded, again matching the service: a deadline six
 * hours in the past is "overdue by 1 day", not "today".
 */
export function dueDistance(dueAt: Date, now: Date): DueDistance {
  const days = Math.floor(
    (dueAt.getTime() - now.getTime()) / (SECONDS_PER_DAY * 1000),
  );
  if (days < 0) {
    return { days, urgency: "overdue" };
  }
  return { days, urgency: days === 0 ? "today" : "upcoming" };
}

/**
 * Classify a finished deadline the way the legacy service does.
 *
 * A completion instant decides it when there is one; without one the deadline
 * is missed once its due instant has passed. Note what this makes unreachable
 * on the history surface: `/api/deadline-history` carries no completion
 * timestamp, so the caller there can only pass the due instant itself for a
 * deadline that was reflected on, which is never *after* the due instant.
 * "Late" is therefore a state the legacy page could not render either, and
 * reproducing that is the point — inventing a completion time to fill the gap
 * would tell the learner something nobody recorded.
 */
export function classifyDeadlineOutcome(
  dueAt: Date,
  completedAt: Date | null,
  now: Date,
): DeadlineOutcome {
  if (completedAt !== null) {
    return completedAt.getTime() > dueAt.getTime() ? "late" : "on_time";
  }
  return now.getTime() > dueAt.getTime() ? "missed" : "on_time";
}

/** Hours as the legacy page wrote them: minutes below one hour, else `1.5h`. */
export function formatHours(hours: number): string {
  if (hours < 1) {
    return `${Math.round(hours * 60)}min`;
  }
  return `${hours.toFixed(1)}h`;
}

export function readOutcomeFilter(url: URL): OutcomeFilter {
  const value = url.searchParams.get(OUTCOME_PARAM);
  return DEADLINE_OUTCOMES.find((outcome) => outcome === value) ?? "all";
}

/** Soonest first, which is the order the legacy list sorted into. */
export function sortByDueDate(deadlines: Deadline[]): Deadline[] {
  return [...deadlines].sort(
    (left, right) => dueTime(left.due_at) - dueTime(right.due_at),
  );
}

/** Most recent first, which is the order the legacy history sorted into. */
export function sortByDueDateDescending(deadlines: Deadline[]): Deadline[] {
  return [...deadlines].sort(
    (left, right) => dueTime(right.due_at) - dueTime(left.due_at),
  );
}

export function readDeadlineList(body: unknown): Deadline[] | null {
  const deadlines = arrayField(body, "deadlines");
  return deadlines?.every(isDeadline) ? (deadlines as Deadline[]) : null;
}

export function readWorkload(body: unknown): Workload | null {
  if (!isRecord(body)) {
    return null;
  }
  const required = [
    "total_estimated_hours",
    "total_tracked_hours",
    "remaining_hours",
    "deadline_count",
  ];
  return required.every((field) => typeof body[field] === "number")
    ? (body as Workload)
    : null;
}

export function readCalibrationMetrics(
  body: unknown,
): EffortCalibrationMetric[] | null {
  const metrics = arrayField(body, "metrics");
  return metrics?.every(isMetric)
    ? (metrics as EffortCalibrationMetric[])
    : null;
}

function dueTime(dueAt: Deadline["due_at"]): number {
  return new Date(dueAt).getTime();
}

function isDeadline(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.deadline_type === "string" &&
    typeof value.due_at === "string" &&
    !Number.isNaN(new Date(value.due_at).getTime())
  );
}

function isMetric(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.domain === "string" &&
    typeof value.sample_count === "number" &&
    typeof value.mean_error === "number" &&
    typeof value.mean_absolute_error === "number"
  );
}

function arrayField(body: unknown, field: string): unknown[] | null {
  if (!isRecord(body)) {
    return null;
  }
  const value = body[field];
  return Array.isArray(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * The absolute due date, always read in UTC.
 *
 * The server stores and compares deadlines in UTC and the legacy page printed
 * them in UTC too. Formatting in the browser's zone instead would move a
 * deadline due at 00:30 UTC onto the previous day for a learner in Vancouver,
 * and the phrase beside it — computed from elapsed seconds — would go on
 * disagreeing with it. One zone for both, named in the copy.
 */
export function formatDueDate(dueAt: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(new Date(dueAt));
}
