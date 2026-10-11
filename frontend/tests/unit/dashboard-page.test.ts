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
  it("scopes calibration and sessions to the session tenant, never to a request parameter", async () => {
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
      expect(url).not.toContain("learning_path_id=99");
    }
    for (const url of requested.filter(isCourseScoped)) {
      expect(url).toContain(`learning_path_id=${TENANT_LEARNING_PATH}`);
    }
  });

  it("fetches course labels only when a review is due", async () => {
    const labelRequests = async (reviews: ReviewItem[]) => {
      const fetch = vi.fn(async (url: string) =>
        url.startsWith("/api/review/")
          ? jsonResponse({ learning_path_id: null, reviews })
          : bodyFor(url),
      );
      await load(createEvent({ fetch }) as never);
      return fetch.mock.calls
        .map((call) => String(call[0]))
        .filter((url) => url.startsWith("/api/learning-paths"));
    };

    expect(await labelRequests([])).toHaveLength(0);
    expect(await labelRequests([dueReview("Graphs")])).toHaveLength(1);
  });

  it("asks for every course's reviews, not the selected one's (#161)", async () => {
    const fetch = vi.fn(async (url: string) => bodyFor(url));

    await load(createEvent({ fetch }) as never);

    const reviewRequests = fetch.mock.calls
      .map((call) => String(call[0]))
      .filter((url) => url.startsWith("/api/review/"));
    expect(reviewRequests).toHaveLength(2);
    for (const url of reviewRequests) {
      expect(url).not.toContain("learning_path_id");
    }
  });

  it("lists the other course's due and upcoming reviews with the selected course on GDS, labelled by course", async () => {
    const ep1Review = {
      ...dueReview("Pointers"),
      learning_path_id: 7,
      next_review_at: "2026-10-12T05:29:00Z",
    };
    const fetch = vi.fn(async (url: string) => {
      if (url.startsWith("/api/review/")) {
        return jsonResponse({ learning_path_id: null, reviews: [ep1Review] });
      }
      if (url.startsWith("/api/learning-paths")) {
        return jsonResponse({
          learning_paths: [
            {
              id: 7,
              short_title: "EP1",
              title: "Einführung in die Programmierung 1",
              url: null,
            },
            {
              id: 12,
              short_title: "GDS",
              title: "Grundlagen der Datenstrukturen",
              url: null,
            },
          ],
        });
      }
      return bodyFor(url);
    });

    const data = (await load(createEvent({ fetch }) as never)) as DashboardData;

    expect(data.due.data).toEqual([ep1Review]);
    expect(data.upcoming.data).toEqual([ep1Review]);
    expect(data.courses).toEqual({ 7: "EP1", 12: "GDS" });
    expect(
      data.pressure.reduce((n, bucket) => n + bucket.count, 0),
    ).toBeGreaterThan(0);
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

  it("says plainly when the workspace has no learning path selected", async () => {
    const fetch = vi.fn(async (url: string) => bodyFor(url));
    const event = createEvent({ fetch, learningPathId: null });

    const data = (await load(event as never)) as DashboardData;

    expect(data.learningPathId).toBeNull();
    expect(data.due.status).toBe("ready");
    expect(data.upcoming.status).toBe("ready");
    const requested = fetch.mock.calls.map((call) => String(call[0]));
    expect(requested.filter(isCourseScoped)).toEqual([]);
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

  it("points a learner with no course selected at the picker", () => {
    // #106: this is the page login lands on, and it used to repeat the dead
    // end — "no numeric learning path selected" — with nowhere to go.
    render(DashboardPage, { data: pageData({ learningPathId: null }) });

    expect(
      screen
        .getByRole("link", { name: "Choose a course" })
        .getAttribute("href"),
    ).toBe("/app/study");
    expect(screen.queryByText(/numeric/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Do this next" })).toBeNull();
  });

  it("labels each due review with its course, whichever course is selected", () => {
    render(DashboardPage, {
      data: pageData({
        courses: { 7: "EP1", 12: "GDS" },
        due: readyPanel([
          { ...dueReview("Pointers"), learning_path_id: 7 },
          dueReview("Graphs"),
        ]),
      }),
    });

    const panel = screen.getByRole("region", { name: "Due for review" });
    const items = within(panel).getAllByRole("listitem");
    expect(
      items.map((item) => item.textContent?.replace(/\s+/g, " ").trim()),
    ).toEqual(["Pointers EP1", "Graphs GDS"]);
  });

  it("shows the review panels, and only those, before a course is selected", () => {
    render(DashboardPage, {
      data: pageData({
        courses: { 7: "EP1" },
        due: readyPanel([{ ...dueReview("Pointers"), learning_path_id: 7 }]),
        learningPathId: null,
      }),
    });

    expect(screen.getByRole("link", { name: "Choose a course" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Due for review" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "The week ahead" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Calibration" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Do this next" })).toBeNull();
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
  courses: Record<number, string>;
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
    courses: {} as Record<number, string>,
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

function isCourseScoped(url: string): boolean {
  return (
    url.startsWith("/api/calibration/") || url.startsWith("/api/study/sessions")
  );
}

function bodyFor(url: string): Response {
  if (url.startsWith("/api/learning-paths")) {
    return jsonResponse({ learning_paths: [] });
  }
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
  learningPathId?: string | null;
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
