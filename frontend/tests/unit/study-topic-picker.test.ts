import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import StudyPage from "../../src/routes/study/+page.svelte";
import { actions, load } from "../../src/routes/study/+page.server";
import type {
  TopicConfidence,
  TopicMapping,
  TopicRow,
} from "../../src/lib/content/filters";
import {
  distinctTopics,
  rankTopicsByGap,
} from "../../src/lib/study/topicChoice";
import {
  createActionEvent,
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const STUDY_URL = "http://localhost/app/study";

type StudyData = Exclude<Awaited<ReturnType<typeof load>>, void>;

function topic(
  name: string,
  source: TopicMapping["source"] = "transcript",
): TopicMapping {
  return {
    topic: name,
    learning_path_id: 12,
    source,
    frequency: 1,
    content_items: [],
  };
}

/** A rating whose prediction overshot the score by `gap` (negative: undershot). */
function rating(name: string, gap: number | null): TopicConfidence {
  return {
    topic: name,
    learning_path_id: 12,
    predicted: 0.5,
    actual: gap === null ? null : 0.5 - gap,
    rated_at: "2026-10-01T10:00:00Z",
    calibration_error: gap,
    is_blind_spot: gap !== null && gap > 0.2,
  };
}

function row(name: string, gap: number | null = null): TopicRow {
  return {
    topic: topic(name),
    confidence: gap === null ? null : rating(name, gap),
  };
}

function renderStudy(topics: StudyData["topics"]) {
  return render(StudyPage, {
    data: {
      ...layoutData,
      learningPathId: 12,
      learningPaths: null,
      sessions: [],
      topics,
    } as never,
    form: null,
  });
}

describe("rankTopicsByGap", () => {
  it("puts the topic the learner most overestimated first", () => {
    const ranked = rankTopicsByGap([
      row("Sorting"),
      row("Graphs", 0.1),
      row("Hashing", 0.4),
    ]);

    expect(ranked.map((r) => r.topic.topic)).toEqual([
      "Hashing",
      "Graphs",
      "Sorting",
    ]);
  });

  it("keeps the course's own order where no gap is known, as the CLI falls back", () => {
    const ranked = rankTopicsByGap([
      row("Sorting"),
      row("Graphs", -0.3),
      row("Hashing", null),
    ]);

    expect(ranked.map((r) => r.topic.topic)).toEqual([
      "Sorting",
      "Graphs",
      "Hashing",
    ]);
  });
});

describe("distinctTopics", () => {
  it("keeps the first row of a name listed under two sources", () => {
    const rows = distinctTopics([
      { confidence: null, topic: topic("Schleifen", "transcript") },
      row("Arrays"),
      { confidence: null, topic: topic("Schleifen", "manual") },
    ]);

    expect(rows.map((r) => [r.topic.topic, r.topic.source])).toEqual([
      ["Schleifen", "transcript"],
      ["Arrays", "transcript"],
    ]);
  });
});

describe("study load offers the course's topics", () => {
  it("orders them by gap, largest first", async () => {
    const fetch = vi.fn(async (url: string | URL) => {
      const path = new URL(String(url), STUDY_URL).pathname;
      if (path === "/api/learning-paths/12/topics") {
        return jsonResponse({
          learning_path_id: 12,
          topics: [topic("Sorting"), topic("Graphs"), topic("Hashing")],
        });
      }
      if (path === "/api/learning-paths/12/topics/confidence") {
        return jsonResponse({
          learning_path_id: 12,
          ratings: [rating("Graphs", 0.1), rating("Hashing", 0.4)],
        });
      }
      return jsonResponse({ learning_path_id: 12, sessions: [] });
    });

    const data = (await load(
      createLoadEvent({ fetch, url: STUDY_URL }) as never,
    )) as StudyData;

    expect(data.topics.status).toBe("ready");
    expect(data.topics.data.map((r: TopicRow) => r.topic.topic)).toEqual([
      "Hashing",
      "Graphs",
      "Sorting",
    ]);
  });

  it("offers a topic stored under two sources once, so the picker can render it", async () => {
    const fetch = vi.fn(async (url: string | URL) => {
      const path = new URL(String(url), STUDY_URL).pathname;
      if (path === "/api/learning-paths/12/topics") {
        return jsonResponse({
          learning_path_id: 12,
          topics: [
            topic("Schleifen", "transcript"),
            topic("Arrays"),
            topic("Schleifen", "manual"),
          ],
        });
      }
      if (path === "/api/learning-paths/12/topics/confidence") {
        return jsonResponse({ learning_path_id: 12, ratings: [] });
      }
      return jsonResponse({ learning_path_id: 12, sessions: [] });
    });

    const data = (await load(
      createLoadEvent({ fetch, url: STUDY_URL }) as never,
    )) as StudyData;
    renderStudy(data.topics);

    expect(data.topics.data.map((r: TopicRow) => r.topic.topic)).toEqual([
      "Schleifen",
      "Arrays",
    ]);
    expect(
      screen.getAllByRole("button", { name: "Study this: Schleifen" }),
    ).toHaveLength(1);
  });

  it("reports an unreachable topic list as unavailable rather than empty", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/topics")
        ? new Response(null, { status: 502 })
        : jsonResponse({ learning_path_id: 12, sessions: [] }),
    );

    const data = (await load(
      createLoadEvent({ fetch, url: STUDY_URL }) as never,
    )) as StudyData;

    expect(data.topics.status).toBe("error");
  });
});

describe("study page topic picker", () => {
  it("offers the suggested topic first, each one a button that starts it", () => {
    renderStudy({
      data: [row("Hashing", 0.4), row("Graphs", 0.1), row("Sorting")],
      status: "ready",
    });

    const list = screen.getByRole("list", { name: "Your course's topics" });
    const [first, second] = within(list).getAllByRole("listitem") as [
      HTMLElement,
      HTMLElement,
    ];
    expect(within(first).getByText("Hashing")).toBeTruthy();
    expect(within(first).getByText("Suggested")).toBeTruthy();
    expect(within(second).queryByText("Suggested")).toBeNull();
    expect(
      within(list)
        .getAllByRole("button")
        .map((button) => (button as HTMLButtonElement).value),
    ).toEqual(["Hashing", "Graphs", "Sorting"]);
  });

  it("says the order follows the gap only once a topic has one", () => {
    const summary = /most overshot your score come first/;

    const ranked = renderStudy({
      data: [row("Hashing", 0.4), row("Sorting")],
      status: "ready",
    });
    expect(screen.getByText(summary)).toBeTruthy();
    ranked.unmount();

    renderStudy({ data: [row("Sorting"), row("Graphs")], status: "ready" });
    expect(screen.queryByText(summary)).toBeNull();
    expect(screen.getByText("Suggested")).toBeTruthy();
  });

  it("starts a session as a form action, so it works without JavaScript", () => {
    renderStudy({ data: [row("Graphs")], status: "ready" });

    const start = screen.getByRole("button", { name: "Study this: Graphs" });
    const form = start.closest("form");
    expect(form?.getAttribute("method")).toBe("POST");
    expect(form?.getAttribute("action")).toBe("?/start");
    expect(start.getAttribute("type")).toBe("submit");
    expect(start.getAttribute("name")).toBe("topic");
  });

  it("explains where topics come from and links there instead of an empty field", () => {
    renderStudy({ data: [], status: "ready" });

    expect(screen.getByText("No topics to study yet")).toBeTruthy();
    expect(
      screen.getByText(/Topics come from processed lectures and materials/),
    ).toBeTruthy();
    const open = screen.getByRole("button", { name: "Open your lectures" });
    expect(open.closest("form")?.getAttribute("action")).toBe("/app/content");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Study this/ })).toBeNull();
  });

  it("says the topics could not be loaded rather than that there are none", () => {
    renderStudy({ data: [], status: "error" });

    expect(screen.getByText(/could not be loaded just now/)).toBeTruthy();
    expect(screen.queryByText("No topics to study yet")).toBeNull();
  });
});

describe("study start action", () => {
  it("starts the session on exactly the topic that was chosen", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url) === "/api/study/sessions"
        ? jsonResponse({ session: { id: 41, topic: "Graphen & Bäume" } })
        : jsonResponse({ questions: [] }),
    );

    await expect(
      actions.start?.(
        createActionEvent({
          fetch,
          form: { topic: "Graphen & Bäume" },
          url: `${STUDY_URL}?/start`,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/study/41/predict", status: 303 });

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/study/sessions");
    expect(JSON.parse(String(init.body))).toEqual({
      learning_path_id: 12,
      topic: "Graphen & Bäume",
    });
  });

  it("asks for a topic instead of starting a session on nothing", async () => {
    const fetch = vi.fn();

    const result = await actions.start?.(
      createActionEvent({
        fetch,
        form: {},
        url: `${STUDY_URL}?/start`,
      }) as never,
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      data: { error: "study.topic_required" },
      status: 400,
    });
  });
});
