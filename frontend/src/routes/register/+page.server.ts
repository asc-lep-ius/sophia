import { fail, redirect, type Actions, type RequestEvent } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import { unavailablePanel, type Panel } from "$lib/dashboard/panels";
import {
  isCourseNumber,
  readAttemptResult,
  readConnectionState,
  readCourseNumber,
  readExamDates,
  readFavorites,
  readGroups,
  readTarget,
  type TissAttemptResult,
  type TissConnectionState,
  type TissExamDate,
  type TissFavorite,
  type TissGroup,
  type TissTarget,
} from "$lib/registration/tiss";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export type CourseDetail = {
  courseNumber: string;
  exams: TissExamDate[];
  groups: TissGroup[];
  target: TissTarget | null;
};

export const load: PageServerLoad = async (event) => {
  requireAuthenticated(event);

  const favorites = await loadFavorites(event);
  const courseNumber = readCourseNumber(event.url);

  return {
    connection: favorites.connection,
    // A course is only opened once TISS is actually reachable: the detail
    // calls would otherwise each report the same missing session as their own
    // failure, three times over.
    detail:
      courseNumber === null || favorites.connection !== "connected"
        ? null
        : await loadCourseDetail(event, courseNumber),
    favorites: favorites.panel,
    now: new Date().toISOString(),
    selectedCourse: courseNumber,
  };
};

export const actions: Actions = {
  register: async (event) => {
    requireAuthenticated(event);

    const formData = await event.request.formData();
    const courseNumber = readFormString(formData, "course_number");
    const groupId = readFormString(formData, "group_id");

    // Checked here so a mistyped number is a message rather than a round trip.
    // The API validates the same shape; this never replaces that.
    if (!isCourseNumber(courseNumber)) {
      return fail(422, { error: "course_number" as const });
    }

    let response: Response;
    try {
      response = await apiFetch(
        event,
        "/api/integrations/tiss/registration/attempts",
        {
          body: JSON.stringify({
            course_number: courseNumber,
            group_id: groupId === "" ? null : groupId,
          }),
          headers: { "content-type": "application/json" },
          method: "POST",
        },
      );
    } catch {
      return fail(502, { error: "unavailable" as const });
    }

    if (response.status === 401) {
      redirect(303, "/app/login");
    }
    if (!response.ok) {
      return fail(safeFailureStatus(response.status), {
        error: "unavailable" as const,
      });
    }

    const body: unknown = await safeJson(response);
    const connection = readConnectionState(body);
    if (connection !== null && connection !== "connected") {
      return fail(422, { error: "session" as const });
    }

    const result = readAttemptResult(body);
    if (result === null) {
      return fail(502, { error: "unavailable" as const });
    }
    return { result } satisfies { result: TissAttemptResult };
  },
};

type FavoritesLoad = {
  connection: TissConnectionState;
  panel: Panel<TissFavorite[]>;
};

async function loadFavorites(event: ApiEvent): Promise<FavoritesLoad> {
  let response: Response;
  try {
    response = await apiFetch(
      event,
      "/api/integrations/tiss/registration/favorites",
    );
  } catch {
    return {
      connection: "connected",
      panel: unavailablePanel<TissFavorite[]>([]),
    };
  }

  if (response.status === 401 || response.status === 403) {
    return {
      connection: "connected",
      panel: { data: [], status: "unauthorized" },
    };
  }
  if (!response.ok) {
    return {
      connection: "connected",
      panel: unavailablePanel<TissFavorite[]>([]),
    };
  }

  const body: unknown = await safeJson(response);
  const parsed = readFavorites(body);
  if (parsed === null) {
    return {
      connection: "connected",
      panel: unavailablePanel<TissFavorite[]>([]),
    };
  }
  return {
    connection: parsed.connection,
    panel: { data: parsed.favorites, status: "ready" },
  };
}

/**
 * The three reads one course needs, fetched together and independently.
 *
 * A course with no exam dates and a course whose exam-date call failed both
 * contribute an empty list here; what keeps them apart on the page is the
 * target, which is null only when TISS could not answer at all.
 */
async function loadCourseDetail(
  event: ApiEvent,
  courseNumber: string,
): Promise<CourseDetail> {
  const [target, groups, exams] = await Promise.all([
    readOrNull(event, courseNumber, "target"),
    readOrNull(event, courseNumber, "groups"),
    readOrNull(event, courseNumber, "exams"),
  ]);

  return {
    courseNumber,
    exams: (exams as TissExamDate[] | null) ?? [],
    groups: (groups as TissGroup[] | null) ?? [],
    target: target as TissTarget | null,
  };
}

async function readOrNull(
  event: ApiEvent,
  courseNumber: string,
  kind: "target" | "groups" | "exams",
): Promise<TissTarget | TissGroup[] | TissExamDate[] | null> {
  try {
    const response = await fetchCourseResource(event, courseNumber, kind);
    if (!response.ok) {
      return null;
    }
    const body: unknown = await safeJson(response);
    if (kind === "target") {
      return readTarget(body);
    }
    return kind === "groups" ? readGroups(body) : readExamDates(body);
  } catch {
    return null;
  }
}

/**
 * The three generated path literals, kept literal.
 *
 * Building one of these by concatenation would type-check against nothing and
 * drift silently when a route is renamed, which is what the API-client guard
 * exists to prevent.
 */
function fetchCourseResource(
  event: ApiEvent,
  courseNumber: string,
  kind: "target" | "groups" | "exams",
): Promise<Response> {
  const params = { course_number: courseNumber };
  if (kind === "target") {
    return apiFetch(
      event,
      "/api/integrations/tiss/registration/targets/{course_number}",
      { params },
    );
  }
  if (kind === "groups") {
    return apiFetch(
      event,
      "/api/integrations/tiss/registration/targets/{course_number}/groups",
      { params },
    );
  }
  return apiFetch(
    event,
    "/api/integrations/tiss/registration/targets/{course_number}/exam-dates",
    { params },
  );
}

function readFormString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function requireAuthenticated(event: RequestEvent): void {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }
}

function safeFailureStatus(status: number): 400 | 401 | 403 | 422 | 502 {
  if (status === 401 || status === 403 || status === 422) {
    return status;
  }
  if (status >= 400 && status < 500) {
    return 400;
  }
  return 502;
}
