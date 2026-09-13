import { render, screen, within } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import { load as layoutLoad } from "../../src/routes/quickstart/+layout.server";
import { actions as predictActions } from "../../src/routes/quickstart/predict/+page.server";
import { actions as topicActions } from "../../src/routes/quickstart/topics/+page.server";
import TopicsStep from "../../src/routes/quickstart/topics/+page.svelte";
import {
  QUICKSTART_STEPS,
  stepFromPath,
  stepNumber,
} from "../../src/lib/quickstart/steps";
import {
  parseTopicLines,
  readConfidenceRatings,
} from "../../src/lib/quickstart/topics";

const TENANT_LEARNING_PATH = "12";

type QuickstartTopic = {
  frequency: number;
  learning_path_id: number;
  source: "manual";
  topic: string;
};

type QuickstartLayoutData = {
  learningPathId: number | null;
  status: "ready" | "unauthorized" | "error";
  topics: QuickstartTopic[];
};

/** What the root layout load contributes to every page's data. */
const rootLayoutData = {
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

type ApiCall = [string, RequestInit | undefined];

describe("quickstart step routing", () => {
  it("reads the step out of the URL, which is where the wizard keeps it", () => {
    expect(stepFromPath("/app/quickstart/topics")).toBe("topics");
    expect(stepFromPath("/app/quickstart/predict/")).toBe("predict");
    expect(stepNumber("done")).toBe(QUICKSTART_STEPS.length);
  });

  it("falls back to the first step for a path that names no step", () => {
    expect(stepFromPath("/app/quickstart")).toBe("welcome");
    expect(stepFromPath("/app/quickstart/nonsense")).toBe("welcome");
  });

  it("keeps no module-level state, so two sessions cannot see each other", async () => {
    const source = await import("../../src/lib/quickstart/steps");

    // Everything exported is a pure function or a frozen-in-practice list of
    // step names; a mutable store here would be shared across SSR requests.
    for (const [name, value] of Object.entries(source)) {
      if (name === "QUICKSTART_STEPS") {
        continue;
      }
      expect(typeof value).toBe("function");
    }
  });
});

describe("quickstart topic parsing", () => {
  it("takes one topic per line and drops repeats and blanks", () => {
    expect(parseTopicLines("Graphs\n\n  Sorting  \ngraphs\n")).toEqual([
      "Graphs",
      "Sorting",
    ]);
  });

  it("keeps only ratings for topics the learner actually has", () => {
    const form = new FormData();
    form.set("rating:Graphs", "4");
    form.set("rating:Injected", "5");
    form.set("rating:Sorting", "9");
    form.set("unrelated", "3");

    expect(readConfidenceRatings(form, ["Graphs", "Sorting"])).toEqual({
      Graphs: 4,
    });
  });
});

describe("quickstart layout load", () => {
  it("asks the API for the session's own overview, never for a named path", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ learning_path_id: 12, topics: [{ topic: "Graphs" }] }),
      );
    const event = createEvent({
      fetch,
      url: "http://localhost/app/quickstart/topics?learning_path_id=99",
    });

    const data = (await layoutLoad(event as never)) as QuickstartLayoutData;

    expect(apiCalls(fetch)[0]?.[0]).toBe("/api/quickstart/overview");
    expect(data.topics.map((entry) => entry.topic)).toEqual(["Graphs"]);
  });

  it("treats a 404 as a first run rather than a failure", async () => {
    const event = createEvent({
      fetch: vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
    });

    const data = (await layoutLoad(event as never)) as QuickstartLayoutData;

    expect(data.status).toBe("ready");
    expect(data.topics).toEqual([]);
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    const event = createEvent({ authenticated: false, fetch: vi.fn() });

    await expect(layoutLoad(event as never)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });
});

describe("quickstart actions", () => {
  it("saves typed topics and moves the URL on to the next step", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ topics: [] }));
    const event = createEvent({
      fetch,
      form: { topics: "Graphs\nSorting" },
    });

    await expect(requireAction(topicActions).save(event)).rejects.toMatchObject(
      {
        location: "/app/quickstart/predict",
        status: 303,
      },
    );

    const [path, init] = apiCalls(fetch)[0] ?? [];
    expect(path).toBe("/api/quickstart/manual-topics");
    expect(JSON.parse(String(init?.body))).toEqual({
      learning_path_id: 12,
      topics: ["Graphs", "Sorting"],
    });
  });

  it("refuses an empty topic list rather than posting one", async () => {
    const fetch = vi.fn();
    const event = createEvent({ fetch, form: { topics: "   \n  " } });

    const result = await requireAction(topicActions).save(event);

    expect(result).toMatchObject({
      data: { error: "quickstart.topics_required" },
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rates only topics the API confirms the learner has", async () => {
    const fetch = vi.fn(async (url: string) =>
      url === "/api/quickstart/overview"
        ? jsonResponse({ learning_path_id: 12, topics: [{ topic: "Graphs" }] })
        : jsonResponse({ learning_path_id: 12, saved_count: 1 }),
    );
    const event = createEvent({
      fetch,
      form: { "rating:Graphs": "4", "rating:SomebodyElse": "5" },
    });

    await expect(
      requireAction(predictActions).save(event),
    ).rejects.toMatchObject({ location: "/app/quickstart/done", status: 303 });

    const save = apiCalls(fetch).find(
      (call) => call[0] === "/api/quickstart/confidence",
    );
    expect(JSON.parse(String(save?.[1]?.body))).toEqual({
      learning_path_id: 12,
      ratings: { Graphs: 4 },
    });
  });
});

describe("quickstart topics step", () => {
  it("lists the topics already known and still offers to add more", () => {
    render(TopicsStep, {
      data: {
        ...rootLayoutData,
        learningPathId: 12,
        status: "ready" as const,
        topics: [topic("Graphs")],
      },
      form: null,
    });

    const step = screen.getByRole("region", { name: "Your topics" });
    expect(within(step).getByText("Graphs")).toBeTruthy();
    expect(within(step).getByLabelText("Topics you expect")).toBeTruthy();
    expect(
      within(step)
        .getByRole("link", { name: "Skip this step" })
        .getAttribute("href"),
    ).toBe("/app/quickstart/predict");
  });

  it("says so when nothing has been synced yet", () => {
    render(TopicsStep, {
      data: {
        ...rootLayoutData,
        learningPathId: null,
        status: "ready" as const,
        topics: [],
      },
      form: null,
    });

    expect(screen.getByText(/Nothing has been synced yet/)).toBeTruthy();
  });
});

function apiCalls(fetch: ReturnType<typeof vi.fn>): ApiCall[] {
  return fetch.mock.calls as unknown as ApiCall[];
}

function topic(name: string): QuickstartTopic {
  return {
    frequency: 1,
    learning_path_id: 12,
    source: "manual" as const,
    topic: name,
  };
}

function requireAction(actions: Record<string, unknown>) {
  const save = actions.save;
  if (typeof save !== "function") {
    throw new Error("quickstart save action is not configured");
  }
  return { save: save as (event: RequestEvent) => Promise<unknown> };
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
  form,
  url = "http://localhost/app/quickstart",
}: {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  form?: Record<string, string>;
  url?: string;
}): RequestEvent {
  const formData = new FormData();
  for (const [key, value] of Object.entries(form ?? {})) {
    formData.set(key, value);
  }

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
      request_id: "req-quickstart",
      role: "student",
      sessionSettings: null,
      tenant: {
        learning_path_id: TENANT_LEARNING_PATH,
        org_id: "tu-wien",
        role: "student",
      },
      user: null,
    },
    request: new Request(url, {
      body: form ? formData : undefined,
      method: form ? "POST" : "GET",
    }),
    url: new URL(url),
  } as unknown as RequestEvent;
}
