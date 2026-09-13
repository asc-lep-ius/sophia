import { fail, redirect, type Actions, type RequestEvent } from "@sveltejs/kit";
import { apiFetch } from "../../hooks.server";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import {
  DEADLINE_HORIZON_DAYS,
  readDeadlineList,
  readWorkload,
  sortByDueDate,
  type Deadline,
  type Workload,
} from "$lib/chronos/deadlines";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export const load: PageServerLoad = async (event) => {
  requireAuthenticated(event);

  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );
  if (learningPathId === null) {
    return {
      deadlines: unavailablePanel<Deadline[]>([]),
      horizonDays: DEADLINE_HORIZON_DAYS,
      learningPathId,
      // Read once, on the server, and handed to the page. The relative phrase
      // beside each deadline is a function of this instant and the due
      // instant, and computing it from the browser's clock instead would let a
      // wrong system clock quietly reclassify a deadline as overdue.
      now: new Date().toISOString(),
      uiLocale: event.locals.locale,
      workload: unavailablePanel<Workload | null>(null),
    };
  }

  const [deadlines, workload] = await Promise.all([
    loadDeadlines(event, learningPathId),
    loadWorkload(event, learningPathId),
  ]);

  return {
    deadlines: {
      data: sortByDueDate(deadlines.data),
      status: deadlines.status,
    } satisfies Panel<Deadline[]>,
    horizonDays: DEADLINE_HORIZON_DAYS,
    learningPathId,
    now: new Date().toISOString(),
    uiLocale: event.locals.locale,
    workload,
  };
};

export const actions: Actions = {
  /**
   * Pull deadlines from the connected LMS.
   *
   * The legacy page's empty state was "No deadlines synced — sync from TUWEL",
   * so this is part of that state rather than an extra: without it the empty
   * page names an action nobody can take.
   */
  sync: async (event) => {
    requireAuthenticated(event);

    let response: Response;
    try {
      response = await apiFetch(event, "/api/deadlines/sync", {
        method: "POST",
      });
    } catch {
      return fail(502, { syncFailed: true });
    }

    if (response.status === 401) {
      redirect(303, "/app/login");
    }
    if (!response.ok) {
      return fail(safeFailureStatus(response.status), { syncFailed: true });
    }

    const body: unknown = await safeJson(response);
    return { syncedCount: readSyncedCount(body) };
  },

  complete: async (event) => {
    requireAuthenticated(event);

    const learningPathId = numericLearningPathId(
      event.locals.tenant.learning_path_id,
    );
    const formData = await event.request.formData();
    const deadlineId = readFormString(formData, "deadline_id");
    if (deadlineId === "" || learningPathId === null) {
      return fail(400, { completeFailed: true });
    }

    let response: Response;
    try {
      response = await apiFetch(
        event,
        "/api/deadlines/{deadline_id}/complete",
        {
          body: JSON.stringify({ learning_path_id: learningPathId }),
          headers: { "content-type": "application/json" },
          method: "POST",
          params: { deadline_id: deadlineId },
        },
      );
    } catch {
      return fail(502, { completeFailed: true });
    }

    if (response.status === 401) {
      redirect(303, "/app/login");
    }
    if (!response.ok) {
      return fail(safeFailureStatus(response.status), { completeFailed: true });
    }

    return { completedId: deadlineId };
  },
};

async function loadDeadlines(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<Deadline[]>> {
  try {
    const response = await apiFetch(event, "/api/deadlines", {
      query: {
        horizon_days: DEADLINE_HORIZON_DAYS,
        learning_path_id: learningPathId,
      },
    });
    return await panelFromResponse(response, readDeadlineList, []);
  } catch {
    return unavailablePanel([]);
  }
}

async function loadWorkload(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<Workload | null>> {
  try {
    const response = await apiFetch(event, "/api/deadlines/workload", {
      query: {
        horizon_days: DEADLINE_HORIZON_DAYS,
        learning_path_id: learningPathId,
      },
    });
    return await panelFromResponse(response, readWorkload, null);
  } catch {
    return unavailablePanel(null);
  }
}

function readSyncedCount(body: unknown): number {
  if (body === null || typeof body !== "object") {
    return 0;
  }
  const count = (body as Record<string, unknown>).synced_count;
  return typeof count === "number" ? count : 0;
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

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
