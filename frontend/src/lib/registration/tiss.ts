import type { components } from "$lib/api/schema";

export type TissConnectionState = components["schemas"]["TissConnectionState"];
export type TissFavorite = components["schemas"]["TissFavoriteResponse"];
export type TissGroup = components["schemas"]["TissRegistrationGroupResponse"];
export type TissTarget =
  components["schemas"]["TissRegistrationTargetResponse"];
export type TissExamDate = components["schemas"]["TissExamDateResponse"];
export type TissAttemptResult =
  components["schemas"]["TissRegistrationAttemptResultResponse"];

export const COURSE_PARAM = "course";

/**
 * The course-number shape TISS uses, and the one the API validates against.
 *
 * Checked here as well so a mistyped number is a message on the form rather
 * than a 422 round trip. The API's copy is the authoritative one; this is a
 * pre-check, not a second source of truth.
 */
export const COURSE_NUMBER_PATTERN = /^\d{3}\.[A-Za-z0-9]{3}$/;

/** `YYYYS` or `YYYYW`, matching the API's semester validation. */
export const SEMESTER_PATTERN = /^\d{4}[SW]$/;

/** The instant format TISS reports its registration windows in. */
const TISS_DATE_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$/;

const MS_PER_MINUTE = 60_000;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;

export type RegistrationCountdown =
  | { state: "open" }
  | { state: "unknown" }
  | { state: "waiting"; days: number; hours: number; minutes: number };

export function isCourseNumber(value: string): boolean {
  return COURSE_NUMBER_PATTERN.test(value);
}

export function readCourseNumber(url: URL): string | null {
  const value = url.searchParams.get(COURSE_PARAM) ?? "";
  return isCourseNumber(value) ? value : null;
}

/**
 * Parse a TISS registration-window timestamp as UTC.
 *
 * TISS prints a wall-clock time with no zone. Reading it in the browser's zone
 * would make the same window count down differently on two machines, so it is
 * pinned to UTC exactly as the legacy service pinned it — one wrong-by-an-hour
 * answer everywhere beats two answers that disagree.
 */
export function parseTissInstant(value: string | null): Date | null {
  const match = TISS_DATE_PATTERN.exec(value?.trim() ?? "");
  if (!match) {
    return null;
  }
  const [, day, month, year, hour, minute] = match;
  return new Date(
    Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
    ),
  );
}

export function registrationCountdown(
  registrationStart: string | null,
  now: Date,
): RegistrationCountdown {
  const opensAt = parseTissInstant(registrationStart);
  if (opensAt === null) {
    return { state: "unknown" };
  }

  const totalMinutes = Math.floor(
    (opensAt.getTime() - now.getTime()) / MS_PER_MINUTE,
  );
  if (totalMinutes <= 0) {
    return { state: "open" };
  }

  return {
    days: Math.floor(totalMinutes / (MINUTES_PER_HOUR * HOURS_PER_DAY)),
    hours: Math.floor(totalMinutes / MINUTES_PER_HOUR) % HOURS_PER_DAY,
    minutes: totalMinutes % MINUTES_PER_HOUR,
    state: "waiting",
  };
}

/** Groups a learner can still take a place in. */
export function openGroups(groups: TissGroup[]): TissGroup[] {
  return groups.filter((group) => group.status === "open");
}

export function readFavorites(
  body: unknown,
): { connection: TissConnectionState; favorites: TissFavorite[] } | null {
  if (!isRecord(body) || !isConnectionState(body.connection)) {
    return null;
  }
  const favorites = body.favorites;
  if (!Array.isArray(favorites) || !favorites.every(isFavorite)) {
    return null;
  }
  return {
    connection: body.connection,
    favorites: favorites as TissFavorite[],
  };
}

export function readTarget(body: unknown): TissTarget | null {
  if (!isRecord(body)) {
    return null;
  }
  const target = body.target;
  return isTarget(target) ? (target as TissTarget) : null;
}

export function readGroups(body: unknown): TissGroup[] | null {
  if (!isRecord(body)) {
    return null;
  }
  const groups = body.groups;
  return Array.isArray(groups) && groups.every(isGroup)
    ? (groups as TissGroup[])
    : null;
}

export function readExamDates(body: unknown): TissExamDate[] | null {
  if (!isRecord(body)) {
    return null;
  }
  const exams = body.exams;
  return Array.isArray(exams) && exams.every(isExamDate)
    ? (exams as TissExamDate[])
    : null;
}

export function readAttemptResult(body: unknown): TissAttemptResult | null {
  if (!isRecord(body)) {
    return null;
  }
  const result = body.result;
  return isRecord(result) &&
    typeof result.success === "boolean" &&
    typeof result.message === "string"
    ? (result as TissAttemptResult)
    : null;
}

export function readConnectionState(body: unknown): TissConnectionState | null {
  return isRecord(body) && isConnectionState(body.connection)
    ? body.connection
    : null;
}

function isConnectionState(value: unknown): value is TissConnectionState {
  return (
    value === "connected" ||
    value === "session_missing" ||
    value === "session_expired"
  );
}

function isFavorite(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.course_number === "string" &&
    typeof value.title === "string" &&
    typeof value.lva_registered === "boolean"
  );
}

function isTarget(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.course_number === "string" &&
    typeof value.status === "string" &&
    Array.isArray(value.groups)
  );
}

function isGroup(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.group_id === "string" &&
    typeof value.name === "string" &&
    typeof value.status === "string" &&
    typeof value.capacity === "number" &&
    typeof value.enrolled === "number"
  );
}

function isExamDate(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.exam_id === "string" &&
    typeof value.title === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
