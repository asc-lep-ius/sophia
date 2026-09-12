import { render, screen, within } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import TopicsPage from "../../src/routes/topics/+page.svelte";
import { load } from "../../src/routes/topics/+page.server";
import type {
  TopicConfidence,
  TopicMapping,
  TopicRow,
} from "../../src/lib/content/filters";
import type { ContentLanguageState } from "../../src/lib/content/language";
import type { Panel } from "../../src/lib/dashboard/panels";

const TENANT_LEARNING_PATH = "12";

describe("topics server load", () => {
  it("scopes the request to the session tenant, never to a query parameter", async () => {
    const fetch = vi.fn(fetchFixture());
    const event = createEvent({
      fetch,
      url: "http://localhost/app/topics?learning_path_id=99",
    });

    await load(event as never);

    const requested = fetch.mock.calls.map((call) => String(call[0]));
    expect(requested.length).toBeGreaterThan(0);
    for (const url of requested) {
      expect(url).toContain("/learning-paths/12/");
      expect(url).not.toContain("/learning-paths/99/");
    }
  });

  it("applies the URL's filters so the first paint already agrees with them", async () => {
    const event = createEvent({
      fetch: vi.fn(fetchFixture()),
      url: "http://localhost/app/topics?origin=manual",
    });

    const data = (await load(event as never)) as TopicsData;

    expect(data.filters.origin).toBe("manual");
    expect(data.rows.data.map((row) => row.topic.topic)).toEqual([
      "Kombinatorik",
    ]);
    expect(data.totalCount).toBe(3);
  });

  it("filters on whether a topic has a prediction, not on whether one exists", async () => {
    const event = createEvent({
      fetch: vi.fn(fetchFixture()),
      url: "http://localhost/app/topics?rated=unrated",
    });

    const data = (await load(event as never)) as TopicsData;

    expect(data.rows.data.map((row) => row.topic.topic)).toEqual([
      "Sorting",
      "Kombinatorik",
    ]);
  });

  it("keeps unrated topics in the list rather than joining them away", async () => {
    const data = (await load(
      createEvent({ fetch: vi.fn(fetchFixture()) }) as never,
    )) as TopicsData;

    expect(
      data.rows.data.map((row) => row.confidence?.predicted ?? null),
    ).toEqual([0.9, null, null]);
  });

  it("reads the drawer's open state out of the URL", async () => {
    const event = createEvent({
      fetch: vi.fn(fetchFixture()),
      url: "http://localhost/app/topics?filters=open",
    });

    const data = (await load(event as never)) as TopicsData;

    expect(data.drawerOpen).toBe(true);
  });

  it("treats a missing confidence list as nothing rated, not as a failure", async () => {
    const event = createEvent({
      fetch: vi.fn(async (url: string) =>
        String(url).includes("/topics/confidence")
          ? new Response(null, { status: 500 })
          : fetchFixture()(url),
      ),
    });

    const data = (await load(event as never)) as TopicsData;

    expect(data.rows.status).toBe("ready");
    expect(data.rows.data).toHaveLength(3);
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    const event = createEvent({ authenticated: false, fetch: vi.fn() });

    await expect(load(event as never)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });
});

describe("topics page", () => {
  it("puts the filters behind a trigger that submits rather than scripts", () => {
    // The drawer's open state is a URL fact, so the control that opens it is a
    // submit button carrying `filters=open` — which works before hydration.
    render(TopicsPage, { data: pageData({}) });

    const trigger = screen.getByRole("button", { name: "Filters" });
    expect(trigger.getAttribute("type")).toBe("submit");
    expect(trigger.getAttribute("name")).toBe("filters");
    expect(trigger.getAttribute("value")).toBe("open");
    expect(trigger.closest("form")?.getAttribute("method")).toBe("get");
  });

  it("offers to close the drawer once it is open", () => {
    render(TopicsPage, { data: pageData({ drawerOpen: true }) });

    expect(screen.getByRole("button", { name: "Hide filters" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Filters" })).toBeNull();
  });

  it("keeps every filter control inside the GET form that addresses the URL", () => {
    render(TopicsPage, {
      data: pageData({
        filters: { origin: "manual", query: "graph", rated: "unrated" },
      }),
    });

    const form = screen.getByLabelText("Search topics").closest("form");
    expect(form?.getAttribute("method")).toBe("get");
    expect(
      (screen.getByLabelText("Search topics") as HTMLInputElement).value,
    ).toBe("graph");
    expect(
      (screen.getByLabelText("Came from") as HTMLSelectElement).value,
    ).toBe("manual");
    expect(
      (screen.getByLabelText("Prediction") as HTMLSelectElement).value,
    ).toBe("unrated");
  });

  it("marks the topic text with the content language, not the UI locale", () => {
    render(TopicsPage, {
      data: pageData({
        rows: { data: [topicRow("Graphen", 0.9)], status: "ready" },
      }),
    });

    expect(screen.getByText("Graphen").getAttribute("lang")).toBe("de");
  });

  it("says a topic is unpredicted rather than showing it as zero", () => {
    render(TopicsPage, {
      data: pageData({
        rows: { data: [topicRow("Sorting", null)], status: "ready" },
      }),
    });

    const panel = screen.getByRole("region", { name: "Topics" });
    expect(within(panel).getByText("Not predicted")).toBeTruthy();
    expect(within(panel).queryByText("Predicted 0%")).toBeNull();
  });

  it("offers the next action on an empty list and names the filters otherwise", () => {
    render(TopicsPage, { data: pageData({}) });
    expect(screen.getByText("No topics yet")).toBeTruthy();

    render(TopicsPage, {
      data: pageData({
        filters: { origin: "manual", query: "", rated: "all" },
      }),
    });
    expect(screen.getByText("Nothing matches those filters")).toBeTruthy();
  });

  it("says the list is outside the account's scope rather than showing it empty", () => {
    render(TopicsPage, {
      data: pageData({ rows: { data: [], status: "unauthorized" } }),
    });

    const panel = screen.getByRole("region", { name: "Topics" });
    expect(
      within(panel).getByText(/outside what your account may read/),
    ).toBeTruthy();
    expect(within(panel).queryByText("No topics yet")).toBeNull();
  });
});

type TopicsData = {
  contentLanguage: ContentLanguageState;
  drawerOpen: boolean;
  filters: {
    origin: "all" | "manual" | "quiz" | "transcript";
    query: string;
    rated: "all" | "rated" | "unrated";
  };
  learningPathId: number | null;
  rows: Panel<TopicRow[]>;
  totalCount: number;
  uiLocale: "de" | "en";
};

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

function pageData(overrides: Partial<TopicsData>) {
  return {
    ...layoutData,
    contentLanguage: {
      language: "de",
      origin: "learning_path",
      override: null,
    } satisfies ContentLanguageState,
    drawerOpen: false,
    filters: { origin: "all" as const, query: "", rated: "all" as const },
    learningPathId: 12,
    rows: { data: [], status: "ready" } as Panel<TopicRow[]>,
    totalCount: 0,
    uiLocale: "en" as const,
    ...overrides,
  };
}

function topic(name: string, source: TopicMapping["source"]): TopicMapping {
  return { frequency: 2, learning_path_id: 12, source, topic: name };
}

function confidence(name: string, predicted: number): TopicConfidence {
  return {
    actual: null,
    calibration_error: null,
    is_blind_spot: false,
    learning_path_id: 12,
    predicted,
    rated_at: "2026-09-10T09:00:00Z",
    topic: name,
  };
}

function topicRow(name: string, predicted: number | null): TopicRow {
  return {
    confidence: predicted === null ? null : confidence(name, predicted),
    topic: topic(name, "transcript"),
  };
}

function fetchFixture() {
  return async (url: string | URL): Promise<Response> => {
    const href = String(url);
    if (href.includes("/content-language")) {
      return jsonResponse({
        available_translations: [],
        content_language: "de",
        learning_path_id: 12,
        resolved_from: "learning_path",
      });
    }
    if (href.includes("/topics/confidence")) {
      return jsonResponse({
        learning_path_id: 12,
        ratings: [confidence("Graphs", 0.9)],
      });
    }
    return jsonResponse({
      learning_path_id: 12,
      topics: [
        topic("Graphs", "transcript"),
        topic("Sorting", "quiz"),
        topic("Kombinatorik", "manual"),
      ],
    });
  };
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
  url = "http://localhost/app/topics",
}: {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  url?: string;
}): RequestEvent {
  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated,
      csrfToken: "csrf-from-session",
      learning_path_id: TENANT_LEARNING_PATH,
      locale: "en",
      org_id: "tu-wien",
      request_id: "req-topics",
      role: "student",
      sessionSettings: null,
      tenant: {
        learning_path_id: TENANT_LEARNING_PATH,
        org_id: "tu-wien",
        role: "student",
      },
      user: null,
    },
    request: new Request(url),
    url: new URL(url),
  } as unknown as RequestEvent;
}
