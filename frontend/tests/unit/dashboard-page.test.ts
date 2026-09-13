import { render, screen, within } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import DashboardPage from "../../src/routes/dashboard/+page.svelte";
import { load } from "../../src/routes/dashboard/+page.server";
import type {
  CalibrationRating,
  Panel,
  ReviewItem,
  StudySessionItem,
} from "../../src/lib/dashboard/panels";

const TENANT_LEARNING_PATH = "12";

describe("dashboard server load", () => {
  it("scopes every panel to the session tenant, never to a request parameter", async () => {
    const fetch = vi.fn(async (url: string) => bodyFor(url));
    const event = createEvent({
      // A learner poking at the URL must not be able to point a panel at
      // another learning path: the abuse case #99 names.
      fetch,
      url: "http://localhost/app/dashboard?learning_path_id=99",
    });

    await load(event as never);

    const requested = fetch.mock.calls.map((call) => String(call[0]));
    expect(requested).toHaveLength(4);
    for (const url of requested) {
      expect(url).toContain(`learning_path_id=${TENANT_LEARNING_PATH}`);
      expect(url).not.toContain("learning_path_id=99");
    }
  });

  it("marks a refused panel unauthorized and leaves the others current", async () => {
    const event = createEvent({
      fetch: vi.fn(async (url: string) =>
        url.startsWith("/api/calibration/ratings")
          ? new Response(null, { status: 403 })
          : bodyFor(url),
      ),
    });

    const data = (await load(event as never)) as DashboardData;

    expect(data.calibration.status).toBe("unauthorized");
    expect(data.calibration.data).toEqual([]);
    expect(data.due.status).toBe("ready");
  });

  it("marks a panel with an unusable body as failed rather than rendering it", async () => {
    const event = createEvent({
      fetch: vi.fn(async (url: string) =>
        url.startsWith("/api/review/due")
          ? jsonResponse({ reviews: [{ topic: 12 }] })
          : bodyFor(url),
      ),
    });

    const data = (await load(event as never)) as DashboardData;

    expect(data.due.status).toBe("error");
    expect(data.upcoming.status).toBe("ready");
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    const event = createEvent({ authenticated: false, fetch: vi.fn() });

    await expect(load(event as never)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });

  it("says plainly when the workspace has no numeric learning path", async () => {
    const fetch = vi.fn();
    const event = createEvent({
      fetch,
      learningPathId: "default-learning-path",
    });

    const data = (await load(event as never)) as DashboardData;

    expect(data.learningPathId).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("dashboard page", () => {
  it("puts the due reviews above everything else when any are due", () => {
    render(DashboardPage, {
      data: pageData({ due: readyPanel([dueReview("Graphs")]) }),
    });

    const nextAction = screen.getByRole("region", { name: "Do this next" });
    expect(within(nextAction).getByText(/1 reviews are due/)).toBeTruthy();
    expect(
      within(nextAction)
        .getByRole("link", { name: "Start review" })
        .getAttribute("href"),
    ).toBe("/app/review");
  });

  it("sends a learner with no history at all to quickstart", () => {
    render(DashboardPage, { data: pageData({}) });

    const nextAction = screen.getByRole("region", { name: "Do this next" });
    expect(
      within(nextAction)
        .getByRole("link", { name: "Open quickstart" })
        .getAttribute("href"),
    ).toBe("/app/quickstart");
  });

  it("renders a designed empty state instead of an empty panel", () => {
    render(DashboardPage, { data: pageData({}) });

    expect(screen.getByText("Caught up")).toBeTruthy();
    expect(screen.getByText("No sessions yet")).toBeTruthy();
  });

  it("keeps retired-scorer rows out of the calibration figure and says how many", () => {
    render(DashboardPage, {
      data: pageData({
        calibration: readyPanel([
          rating("Graphs", 0.9, 0.4, false),
          rating("Sorting", 0.9, 1, true),
        ]),
      }),
    });

    const panel = screen.getByRole("region", { name: "Calibration" });
    const table = within(panel).getByRole("table");
    expect(
      within(table).getByRole("rowheader", { name: "Graphs" }),
    ).toBeTruthy();
    expect(
      within(table).queryByRole("rowheader", { name: "Sorting" }),
    ).toBeNull();
    expect(within(panel).getByText(/1 topics are left out/)).toBeTruthy();
  });

  it("gives every figure a table carrying the same numbers", () => {
    render(DashboardPage, {
      data: pageData({
        pressure: [
          { count: 3, dayOffset: 0 },
          { count: 1, dayOffset: 1 },
        ],
        upcoming: readyPanel([dueReview("Graphs")]),
      }),
    });

    const panel = screen.getByRole("region", { name: "The week ahead" });
    const table = within(panel).getByRole("table");
    expect(
      within(table).getByRole("rowheader", { name: "Today" }),
    ).toBeTruthy();
    expect(
      within(table).getByRole("rowheader", { name: "In 1 days" }),
    ).toBeTruthy();
    expect(
      within(table)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["3", "1"]);
  });

  it("says which panel could not be read rather than showing it as empty", () => {
    render(DashboardPage, {
      data: pageData({ due: { data: [], status: "error" } }),
    });

    const panel = screen.getByRole("region", { name: "Due for review" });
    expect(within(panel).getByText(/did not answer/)).toBeTruthy();
    expect(within(panel).queryByText("Caught up")).toBeNull();
  });
});

type DashboardData = {
  calibration: Panel<CalibrationRating[]>;
  due: Panel<ReviewItem[]>;
  learningPathId: number | null;
  pressure: { count: number; dayOffset: number }[];
  sessions: Panel<StudySessionItem[]>;
  upcoming: Panel<ReviewItem[]>;
};

/** What the root layout load contributes to every page's data. */
const layoutData = {
  authenticated: true,
  locale: "en",
  settings: null,
  tenant: {
    learning_path_id: TENANT_LEARNING_PATH,
    org_id: "tu-wien",
    role: "student",
  },
  theme: "light",
  user: null,
} as const;

function readyPanel<T>(data: T): Panel<T> {
  return { data, status: "ready" };
}

function pageData(overrides: Partial<DashboardData>) {
  return {
    ...layoutData,
    calibration: readyPanel<CalibrationRating[]>([]),
    due: readyPanel<ReviewItem[]>([]),
    learningPathId: 12,
    pressure: [],
    sessions: readyPanel<StudySessionItem[]>([]),
    upcoming: readyPanel<ReviewItem[]>([]),
    ...overrides,
  };
}

function dueReview(topic: string): ReviewItem {
  return {
    difficulty: 0.3,
    interval_days: 1,
    interval_index: 0,
    is_due: true,
    last_reviewed_at: null,
    learning_path_id: 12,
    next_review_at: "2026-09-12T09:00:00Z",
    review_count: 1,
    score_at_last_review: null,
    stability: 1,
    topic,
  };
}

function rating(
  topic: string,
  predicted: number,
  actual: number | null,
  legacyScored: boolean,
): CalibrationRating {
  return {
    actual,
    calibration_error: actual === null ? null : predicted - actual,
    difficulty_level: "transfer",
    is_blind_spot: false,
    learning_path_id: 12,
    legacy_scored: legacyScored,
    predicted,
    rated_at: "2026-09-10T09:00:00Z",
    topic,
  };
}

function bodyFor(url: string): Response {
  if (
    url.startsWith("/api/review/due") ||
    url.startsWith("/api/review/upcoming")
  ) {
    return jsonResponse({ learning_path_id: 12, reviews: [] });
  }
  if (url.startsWith("/api/calibration/ratings")) {
    return jsonResponse({ learning_path_id: 12, ratings: [] });
  }
  return jsonResponse({ learning_path_id: 12, sessions: [] });
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

function createEvent({
  authenticated = true,
  fetch,
  learningPathId = TENANT_LEARNING_PATH,
  url = "http://localhost/app/dashboard",
}: {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  learningPathId?: string;
  url?: string;
}): RequestEvent {
  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated,
      csrfToken: "csrf-from-session",
      learning_path_id: learningPathId,
      locale: "en",
      org_id: "tu-wien",
      request_id: "req-dashboard",
      role: "student",
      sessionSettings: null,
      tenant: {
        learning_path_id: learningPathId,
        org_id: "tu-wien",
        role: "student",
      },
      user: null,
    },
    request: new Request(url),
    url: new URL(url),
  } as unknown as RequestEvent;
}
