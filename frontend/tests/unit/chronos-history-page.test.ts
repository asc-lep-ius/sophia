import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import HistoryPage from "../../src/routes/chronos/history/+page.svelte";
import { load } from "../../src/routes/chronos/history/+page.server";
import type { PastDeadline } from "../../src/routes/chronos/history/+page.server";
import {
  HISTORY_LIMIT,
  type Deadline,
  type EffortCalibrationMetric,
} from "../../src/lib/chronos/deadlines";
import type { Panel } from "../../src/lib/dashboard/panels";
import {
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const HISTORY_URL = "http://localhost/app/chronos/history";
const NOW = "2026-09-12T09:00:00Z";
const MS_PER_DAY = 86_400_000;

describe("chronos history server load", () => {
  it("asks for one page of history rather than the endpoint's default", async () => {
    const fetch = vi.fn(fetchFixture());

    await load(createLoadEvent({ fetch, url: HISTORY_URL }) as never);

    const listCall = fetch.mock.calls.find((call) =>
      String(call[0]).match(/\/api\/deadline-history\?/),
    );
    expect(String(listCall?.[0])).toContain(`limit=${HISTORY_LIMIT}`);
  });

  /**
   * The legacy service's rule, reproduced exactly: a past deadline that was
   * reflected on counts as finished at its due instant, everything else as
   * never finished. It is the only classification the history data supports.
   */
  it("classifies a reflected deadline on time and an unreflected one missed", async () => {
    const data = (await load(
      createLoadEvent({
        fetch: vi.fn(fetchFixture()),
        url: HISTORY_URL,
      }) as never,
    )) as HistoryData;

    expect(data.rows.data.map((row) => [row.deadline.id, row.outcome])).toEqual(
      [
        ["reflected", "on_time"],
        ["missed", "missed"],
      ],
    );
  });

  it("puts the most recent deadline first", async () => {
    const data = (await load(
      createLoadEvent({
        fetch: vi.fn(fetchFixture()),
        url: HISTORY_URL,
      }) as never,
    )) as HistoryData;

    expect(data.rows.data.map((row) => row.deadline.id)).toEqual([
      "reflected",
      "missed",
    ]);
  });

  it("applies the outcome filter from the URL, counting what it hid", async () => {
    const data = (await load(
      createLoadEvent({
        fetch: vi.fn(fetchFixture()),
        url: `${HISTORY_URL}?outcome=missed`,
      }) as never,
    )) as HistoryData;

    expect(data.rows.data.map((row) => row.deadline.id)).toEqual(["missed"]);
    expect(data.totalCount).toBe(2);
  });

  it("treats a reflection lookup that failed as no reflection, not as a page failure", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/reflection")
        ? new Response(null, { status: 500 })
        : fetchFixture()(url),
    );

    const data = (await load(
      createLoadEvent({ fetch, url: HISTORY_URL }) as never,
    )) as HistoryData;

    expect(data.rows.status).toBe("ready");
    expect(data.rows.data.every((row) => row.outcome === "missed")).toBe(true);
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    await expect(
      load(
        createLoadEvent({
          authenticated: false,
          fetch: vi.fn(),
          url: HISTORY_URL,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/login", status: 303 });
  });
});

describe("chronos history page", () => {
  it("shows the outcome beside each past deadline", () => {
    render(HistoryPage, { data: pageData({ rows: rowsPanel() }) });

    const panel = screen.getByRole("region", { name: "History" });
    expect(within(panel).getByText("On time")).toBeTruthy();
    expect(within(panel).getByText("Missed")).toBeTruthy();
  });

  /**
   * The surface cannot produce a "late" row, because nothing in the history
   * records when a deadline was finished. A learner who never sees one has to
   * be told that, or they will read its absence as never having been late.
   */
  it("says out loud that a late outcome cannot appear here", () => {
    render(HistoryPage, { data: pageData({ rows: rowsPanel() }) });

    expect(screen.getByText(/cannot appear here/)).toBeTruthy();
  });

  it("offers to clear the filter when it is the filter that emptied the list", () => {
    render(HistoryPage, { data: pageData({ outcome: "late", totalCount: 2 }) });

    expect(screen.getByText("No deadlines with that outcome")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Clear filters" })).toBeTruthy();
  });

  it("names the empty history rather than blaming a filter", () => {
    render(HistoryPage, { data: pageData({}) });

    expect(screen.getByText("No past deadlines yet")).toBeTruthy();
  });

  it("flags an estimation figure that rests on too few deadlines", () => {
    render(HistoryPage, {
      data: pageData({
        calibration: {
          data: [metric("assignment", 4), metric("exam", 1)],
          status: "ready",
        },
      }),
    });

    const panel = screen.getByRole("region", { name: "Estimation accuracy" });
    expect(
      within(panel).getByText(/fewer than three finished deadlines/),
    ).toBeTruthy();
  });

  it("carries every figure value in a table beside the drawing", () => {
    render(HistoryPage, {
      data: pageData({
        calibration: { data: [metric("assignment", 4)], status: "ready" },
      }),
    });

    const panel = screen.getByRole("region", { name: "Estimation accuracy" });
    expect(within(panel).getAllByRole("table").length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("assignment").length).toBeGreaterThan(0);
  });
});

type HistoryData = {
  calibration: Panel<EffortCalibrationMetric[]>;
  drawerOpen: boolean;
  learningPathId: number | null;
  limit: number;
  now: string;
  outcome: "all" | "late" | "missed" | "on_time";
  rows: Panel<PastDeadline[]>;
  totalCount: number;
  uiLocale: "de" | "en";
};

function pageData(overrides: Partial<HistoryData>) {
  return {
    ...layoutData,
    calibration: {
      data: [],
      status: "ready",
    } as Panel<EffortCalibrationMetric[]>,
    drawerOpen: false,
    learningPathId: 12,
    limit: HISTORY_LIMIT,
    now: NOW,
    outcome: "all" as const,
    rows: { data: [], status: "ready" } as Panel<PastDeadline[]>,
    totalCount: 0,
    uiLocale: "en" as const,
    ...overrides,
  };
}

function rowsPanel(): Panel<PastDeadline[]> {
  return {
    data: [
      {
        deadline: deadline("reflected", "Abgabe 0", -12.5),
        outcome: "on_time",
        reflected: true,
      },
      {
        deadline: deadline("missed", "Kreuzerl 2", -20.5),
        outcome: "missed",
        reflected: false,
      },
    ],
    status: "ready",
  };
}

function metric(domain: string, sampleCount: number): EffortCalibrationMetric {
  return {
    domain,
    mean_absolute_error: 1.5,
    mean_error: 1.25,
    sample_count: sampleCount,
    trend: "flat",
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
    const href = String(url);
    if (href.includes("/reflection")) {
      return href.includes("/reflected/")
        ? jsonResponse({ deadline_id: "reflected", reflection: {} })
        : new Response(null, { status: 404 });
    }
    if (href.includes("/calibration")) {
      return jsonResponse({
        learning_path_id: 12,
        metrics: [metric("assignment", 4)],
      });
    }
    return jsonResponse({
      deadlines: [
        deadline("missed", "Kreuzerl 2", -20.5),
        deadline("reflected", "Abgabe 0", -12.5),
      ],
      learning_path_id: 12,
      limit: HISTORY_LIMIT,
    });
  };
}
