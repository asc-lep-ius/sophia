import { redirect } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import { readDrawerOpen } from "$lib/content/filters";
import {
  HISTORY_LIMIT,
  classifyDeadlineOutcome,
  readCalibrationMetrics,
  readDeadlineList,
  readOutcomeFilter,
  sortByDueDateDescending,
  type Deadline,
  type DeadlineOutcome,
  type EffortCalibrationMetric,
} from "$lib/chronos/deadlines";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export type PastDeadline = {
  deadline: Deadline;
  outcome: DeadlineOutcome;
  reflected: boolean;
};

export const load: PageServerLoad = async (event) => {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }

  const outcome = readOutcomeFilter(event.url);
  const now = new Date();
  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );

  if (learningPathId === null) {
    return {
      calibration: unavailablePanel<EffortCalibrationMetric[]>([]),
      drawerOpen: readDrawerOpen(event.url),
      learningPathId,
      limit: HISTORY_LIMIT,
      now: now.toISOString(),
      outcome,
      rows: unavailablePanel<PastDeadline[]>([]),
      totalCount: 0,
      uiLocale: event.locals.locale,
    };
  }

  const [past, calibration] = await Promise.all([
    loadPastDeadlines(event, learningPathId),
    loadCalibration(event, learningPathId),
  ]);

  const classified = await classify(
    event,
    sortByDueDateDescending(past.data),
    now,
  );

  return {
    calibration,
    drawerOpen: readDrawerOpen(event.url),
    learningPathId,
    limit: HISTORY_LIMIT,
    now: now.toISOString(),
    outcome,
    rows: {
      data: classified.filter(
        (row) => outcome === "all" || row.outcome === outcome,
      ),
      status: past.status,
    } satisfies Panel<PastDeadline[]>,
    totalCount: classified.length,
    uiLocale: event.locals.locale,
  };
};

/**
 * Attach the legacy service's outcome to each past deadline.
 *
 * The classifier takes a completion instant, and the history endpoint does not
 * carry one — so, exactly as the legacy page did, a deadline that was
 * reflected on is treated as completed at its due instant and everything else
 * as uncompleted. That makes "late" unreachable here, which is the legacy
 * behaviour rather than an oversight: nothing in this data records *when* a
 * deadline was finished, and inventing a time to fill the gap would put a
 * judgement in front of the learner that no record supports.
 */
async function classify(
  event: ApiEvent,
  deadlines: Deadline[],
  now: Date,
): Promise<PastDeadline[]> {
  return Promise.all(
    deadlines.map(async (deadline) => {
      const reflected = await hasReflection(event, deadline.id);
      const dueAt = new Date(deadline.due_at);
      return {
        deadline,
        outcome: classifyDeadlineOutcome(dueAt, reflected ? dueAt : null, now),
        reflected,
      };
    }),
  );
}

async function hasReflection(
  event: ApiEvent,
  deadlineId: string,
): Promise<boolean> {
  try {
    const response = await apiFetch(
      event,
      "/api/deadline-history/{deadline_id}/reflection",
      { params: { deadline_id: deadlineId } },
    );
    return response.ok;
  } catch {
    return false;
  }
}

async function loadPastDeadlines(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<Deadline[]>> {
  try {
    const response = await apiFetch(event, "/api/deadline-history", {
      query: { learning_path_id: learningPathId, limit: HISTORY_LIMIT },
    });
    return await panelFromResponse(response, readDeadlineList, []);
  } catch {
    return unavailablePanel([]);
  }
}

async function loadCalibration(
  event: ApiEvent,
  learningPathId: number,
): Promise<Panel<EffortCalibrationMetric[]>> {
  try {
    const response = await apiFetch(
      event,
      "/api/deadline-history/calibration",
      {
        query: { learning_path_id: learningPathId },
      },
    );
    return await panelFromResponse(response, readCalibrationMetrics, []);
  } catch {
    return unavailablePanel([]);
  }
}

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
