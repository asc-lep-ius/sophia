import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import ChronosPage from "../../src/routes/chronos/+page.svelte";
import { actions, load } from "../../src/routes/chronos/+page.server";
import {
  DEADLINE_HORIZON_DAYS,
  type Deadline,
  type Workload,
} from "../../src/lib/chronos/deadlines";
import type { Panel } from "../../src/lib/dashboard/panels";
import {
  createActionEvent,
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const CHRONOS_URL = "http://localhost/app/chronos";
const NOW = "2026-09-12T09:00:00Z";
const MS_PER_DAY = 86_400_000;

describe("chronos server load", () => {
  it("asks for the horizon the legacy page asked for, not the endpoint default", async () => {
    const fetch = vi.fn(fetchFixture());

    await load(createLoadEvent({ fetch, url: CHRONOS_URL }) as never);

    for (const call of fetch.mock.calls) {
      expect(String(call[0])).toContain(
        `horizon_days=${DEADLINE_HORIZON_DAYS}`,
      );
    }
  });

  it("scopes the request on the session tenant, not on the query string", async () => {
    const fetch = vi.fn(fetchFixture());

    await load(
      createLoadEvent({
        fetch,
        url: `${CHRONOS_URL}?learning_path_id=99`,
      }) as never,
    );

    for (const call of fetch.mock.calls) {
      expect(String(call[0])).toContain("learning_path_id=12");
      expect(String(call[0])).not.toContain("learning_path_id=99");
    }
  });

  it("sorts the deadlines soonest first", async () => {
    const data = (await load(
      createLoadEvent({
        fetch: vi.fn(fetchFixture()),
        url: CHRONOS_URL,
      }) as never,
    )) as ChronosData;

    expect(data.deadlines.data.map((entry) => entry.id)).toEqual([
      "overdue",
      "today",
      "week",
    ]);
  });

  /**
   * The instant the phrases are measured against is read once on the server.
   * Taking it from the browser would let a wrong system clock reclassify a
   * deadline as overdue without anything upstream having changed.
   */
  it("carries the server's instant rather than leaving it to the browser", async () => {
    const data = (await load(
      createLoadEvent({
        fetch: vi.fn(fetchFixture()),
        url: CHRONOS_URL,
      }) as never,
    )) as ChronosData;

    expect(Number.isNaN(new Date(data.now).getTime())).toBe(false);
  });

  it("keeps the deadline list readable when the workload call fails", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/workload")
        ? new Response(null, { status: 500 })
        : fetchFixture()(url),
    );

    const data = (await load(
      createLoadEvent({ fetch, url: CHRONOS_URL }) as never,
    )) as ChronosData;

    expect(data.workload.status).toBe("error");
    expect(data.deadlines.status).toBe("ready");
    expect(data.deadlines.data).toHaveLength(3);
  });

  it("asks for nothing when the workspace has no learning path selected", async () => {
    const fetch = vi.fn();

    const data = (await load(
      createLoadEvent({
        fetch,
        learningPathId: null,
        url: CHRONOS_URL,
      }) as never,
    )) as ChronosData;

    expect(fetch).not.toHaveBeenCalled();
    expect(data.learningPathId).toBeNull();
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    await expect(
      load(
        createLoadEvent({
          authenticated: false,
          fetch: vi.fn(),
          url: CHRONOS_URL,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/login", status: 303 });
  });
});

describe("chronos actions", () => {
  it("reports how many deadlines a sync brought in", async () => {
    const fetch = vi.fn(async () =>
      jsonResponse({ deadlines: [], synced_count: 4 }),
    );

    const result = await actions.sync?.(
      createActionEvent({ fetch, form: {}, url: CHRONOS_URL }) as never,
    );

    expect(result).toEqual({ syncedCount: 4 });
  });

  it("says a sync failed rather than reporting zero deadlines", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/api/deadlines/sync")
        ? new Response(null, { status: 502 })
        : new Response(null, { status: 404 }),
    );

    const result = await actions.sync?.(
      createActionEvent({ fetch, form: {}, url: CHRONOS_URL }) as never,
    );

    expect(result).toMatchObject({ data: { syncFailed: true }, status: 502 });
  });

  it("completes a deadline through its own scoped route", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/complete")
        ? jsonResponse({
            actual_hours: 4,
            completed: true,
            deadline_id: "dl-1",
            feedback: "",
            predicted_hours: 3,
          })
        : new Response(null, { status: 404 }),
    );

    const result = await actions.complete?.(
      createActionEvent({
        fetch,
        form: { deadline_id: "dl-1" },
        url: CHRONOS_URL,
      }) as never,
    );

    expect(fetch.mock.calls.map((call) => String(call[0]))).toEqual([
      "/api/deadlines/dl-1/complete",
    ]);
    expect(result).toEqual({ completedId: "dl-1" });
  });

  it("refuses a completion with no deadline, without spending a request", async () => {
    const fetch = vi.fn();

    const result = await actions.complete?.(
      createActionEvent({ fetch, form: {}, url: CHRONOS_URL }) as never,
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(result).toMatchObject({ status: 400 });
  });
});

describe("chronos page", () => {
  it("says how far away each deadline is and when it is due in UTC", () => {
    render(ChronosPage, {
      data: pageData({
        deadlines: {
          data: [deadline("dl-1", "Quiz 3", 5.5)],
          status: "ready",
        },
      }),
      form: null,
    });

    expect(screen.getByText("Due in 5 days")).toBeTruthy();
    expect(screen.getByText(/UTC/)).toBeTruthy();
  });

  it("marks an overdue deadline as overdue rather than as due in zero days", () => {
    render(ChronosPage, {
      data: pageData({
        deadlines: {
          data: [deadline("dl-1", "Abgabe 1", -1.5)],
          status: "ready",
        },
      }),
      form: null,
    });

    expect(screen.getByText("Overdue by 2 days")).toBeTruthy();
  });

  it("offers the sync the empty state names", () => {
    render(ChronosPage, { data: pageData({}), form: null });

    const panel = screen.getByRole("region", { name: "Upcoming" });
    expect(within(panel).getByText("No deadlines synced")).toBeTruthy();
    const button = within(panel).getByRole("button", {
      name: "Sync deadlines",
    });
    expect(button.closest("form")?.getAttribute("action")).toBe("?/sync");
  });

  it("says the list is outside the account's scope rather than showing it empty", () => {
    render(ChronosPage, {
      data: pageData({ deadlines: { data: [], status: "unauthorized" } }),
      form: null,
    });

    const panel = screen.getByRole("region", { name: "Upcoming" });
    expect(
      within(panel).getByText(/outside what your account may read/),
    ).toBeTruthy();
    expect(within(panel).queryByText("No deadlines synced")).toBeNull();
  });

  it("says a sync that changed nothing did so", () => {
    render(ChronosPage, {
      data: pageData({}),
      form: { syncedCount: 0 },
    });

    expect(screen.getByRole("status").textContent).toContain(
      "found no deadlines",
    );
  });

  it("reports a failed sync as a failure, not as an empty result", () => {
    render(ChronosPage, { data: pageData({}), form: { syncFailed: true } });

    expect(screen.getByRole("alert").textContent).toContain("did not finish");
  });

  it("links to the history rather than hiding it behind the nav", () => {
    render(ChronosPage, { data: pageData({}), form: null });

    expect(
      screen.getByRole("link", { name: "See past deadlines" }),
    ).toBeTruthy();
  });
});

type ChronosData = {
  deadlines: Panel<Deadline[]>;
  horizonDays: number;
  learningPathId: number | null;
  now: string;
  uiLocale: "de" | "en";
  workload: Panel<Workload | null>;
};

function pageData(overrides: Partial<ChronosData>) {
  return {
    ...layoutData,
    deadlines: { data: [], status: "ready" } as Panel<Deadline[]>,
    horizonDays: DEADLINE_HORIZON_DAYS,
    learningPathId: 12,
    now: NOW,
    uiLocale: "en" as const,
    workload: { data: null, status: "ready" } as Panel<Workload | null>,
    ...overrides,
  };
}

function deadline(id: string, name: string, dayOffset: number): Deadline {
  return {
    deadline_type: "assignment",
    due_at: new Date(
      new Date(NOW).getTime() + dayOffset * MS_PER_DAY,
    ).toISOString(),
    extra: {},
    grade_weight: null,
    id,
    learning_path_id: 12,
    learning_path_name: "AlgoDat",
    name,
    submission_status: null,
    url: null,
  } as Deadline;
}

function fetchFixture() {
  return async (url: string | URL): Promise<Response> => {
    if (String(url).includes("/workload")) {
      return jsonResponse({
        deadline_count: 3,
        horizon_days: DEADLINE_HORIZON_DAYS,
        learning_path_id: 12,
        per_day: [],
        remaining_hours: 5.5,
        total_estimated_hours: 9.5,
        total_tracked_hours: 4,
      });
    }
    return jsonResponse({
      deadlines: [
        deadline("week", "Exam", 5.5),
        deadline("overdue", "Abgabe", -2.5),
        deadline("today", "Quiz", 0.5),
      ],
      horizon_days: DEADLINE_HORIZON_DAYS,
      learning_path_id: 12,
    });
  };
}
