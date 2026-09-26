import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import StudyPage from "../../src/routes/study/+page.svelte";
import { actions, load } from "../../src/routes/study/+page.server";
import {
  createActionEvent,
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const STUDY_URL = "http://localhost/app/study";

const ALGORITHMS = {
  id: 12,
  short_title: "186.813",
  title: "Algorithms",
  url: null,
};
const DATABASES = {
  id: 34,
  short_title: "184.686",
  title: "Databases",
  url: null,
};

type StudyData = Exclude<Awaited<ReturnType<typeof load>>, void>;

function apiFetchFixture(learningPaths: unknown[] = [ALGORITHMS, DATABASES]) {
  return vi.fn(async (url: string | URL) => {
    const path = String(url);
    if (path.startsWith("/api/learning-paths")) {
      return jsonResponse({
        learning_path_id: null,
        learning_paths: learningPaths,
      });
    }
    if (path.startsWith("/api/study/sessions")) {
      return jsonResponse({ learning_path_id: 12, sessions: [] });
    }
    return new Response(null, { status: 404 });
  });
}

function calledPaths(fetch: ReturnType<typeof vi.fn>): string[] {
  return fetch.mock.calls.map(
    (call) => new URL(String(call[0]), STUDY_URL).pathname,
  );
}

describe("study load", () => {
  it("offers the learner's learning paths when none is selected", async () => {
    const fetch = apiFetchFixture();

    const data = (await load(
      createLoadEvent({ fetch, learningPathId: null, url: STUDY_URL }) as never,
    )) as StudyData;

    expect(calledPaths(fetch)).toEqual(["/api/learning-paths"]);
    expect(data.learningPathId).toBeNull();
    expect(data.learningPaths).toEqual({
      data: [ALGORITHMS, DATABASES],
      status: "ready",
    });
  });

  it("studies the selection without asking TUWEL for the list", async () => {
    const fetch = apiFetchFixture();

    const data = (await load(
      createLoadEvent({ fetch, url: STUDY_URL }) as never,
    )) as StudyData;

    expect(calledPaths(fetch)).toEqual(["/api/study/sessions"]);
    expect(data.learningPathId).toBe(12);
    expect(data.learningPaths).toBeNull();
  });

  it("reopens the picker over a selection when asked to", async () => {
    const fetch = apiFetchFixture();

    const data = (await load(
      createLoadEvent({ fetch, url: `${STUDY_URL}?choose=1` }) as never,
    )) as StudyData;

    expect(calledPaths(fetch)).toEqual(["/api/learning-paths"]);
    expect(data.learningPathId).toBe(12);
    expect(data.learningPaths?.status).toBe("ready");
  });

  it("reports an unreachable list as unavailable rather than empty", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 502 }));

    const data = (await load(
      createLoadEvent({ fetch, learningPathId: null, url: STUDY_URL }) as never,
    )) as StudyData;

    expect(data.learningPaths).toEqual({ data: [], status: "error" });
  });
});

describe("study select action", () => {
  it("scopes the session to the picked learning path, then reloads", async () => {
    const fetch = vi.fn(async () => jsonResponse({ learning_path_id: 34 }));

    await expect(
      actions.select?.(
        createActionEvent({
          fetch,
          form: { learning_path_id: "34" },
          learningPathId: null,
          url: STUDY_URL,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/study", status: 303 });

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/learning-paths/selection");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(JSON.stringify({ learning_path_id: 34 }));
    expect(headers.get("x-csrf-token")).toBe("csrf-from-session");
  });

  it.each<Record<string, string>>([
    {},
    { learning_path_id: "" },
    { learning_path_id: "NaN" },
  ])("asks for a choice instead of sending %j", async (form) => {
    const fetch = vi.fn();

    const result = await actions.select?.(
      createActionEvent({
        fetch,
        form,
        learningPathId: null,
        url: STUDY_URL,
      }) as never,
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      data: { error: "study.learning_path_required" },
      status: 400,
    });
  });

  it("says so when the API refuses the choice", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 404 }));

    const result = await actions.select?.(
      createActionEvent({
        fetch,
        form: { learning_path_id: "99" },
        learningPathId: null,
        url: STUDY_URL,
      }) as never,
    );

    expect(result).toMatchObject({
      data: { error: "study.learning_path_select_failed" },
      status: 404,
    });
  });
});

describe("study page picker", () => {
  function renderStudy(data: Partial<StudyData>) {
    return render(StudyPage, {
      data: {
        ...layoutData,
        learningPathId: null,
        learningPaths: null,
        sessions: [],
        ...data,
      } as never,
      form: null,
    });
  }

  it("lists each learning path as a choice to study", () => {
    renderStudy({
      learningPaths: { data: [ALGORITHMS, DATABASES], status: "ready" },
    });

    const choices = screen.getByRole("group", { name: "Your courses" });
    expect(
      within(choices)
        .getAllByRole("radio")
        .map((radio) => (radio as HTMLInputElement).value),
    ).toEqual(["12", "34"]);
    expect(within(choices).getByText("Algorithms")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Study this course" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start session" })).toBeNull();
  });

  it("checks the current selection when the picker is reopened", () => {
    renderStudy({
      learningPathId: 34,
      learningPaths: { data: [ALGORITHMS, DATABASES], status: "ready" },
    });

    const current = screen.getByRole("radio", { name: /Databases/ });
    expect((current as HTMLInputElement).checked).toBe(true);
    expect(
      screen
        .getByRole("link", { name: "Keep the current course" })
        .getAttribute("href"),
    ).toBe("/app/study");
  });

  it("sends the learner to sync when there is nothing to choose", () => {
    renderStudy({ learningPaths: { data: [], status: "ready" } });

    expect(screen.getByText("No courses to study yet")).toBeTruthy();
    const sync = screen.getByRole("button", { name: "Sync from TUWEL" });
    expect(sync.closest("form")?.getAttribute("action")).toBe(
      "/app/content/sources",
    );
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("says the list could not be loaded instead of showing it empty", () => {
    renderStudy({ learningPaths: { data: [], status: "error" } });

    expect(
      screen.getByText(/could not be loaded from TUWEL just now/),
    ).toBeTruthy();
    expect(screen.queryByText("No courses to study yet")).toBeNull();
  });

  it("offers to change the course once one is being studied", () => {
    renderStudy({ learningPathId: 12 });

    const change = screen.getByRole("button", { name: "Change course" });
    const form = change.closest("form");
    expect(form?.getAttribute("action")).toBe("/app/study");
    expect(form?.querySelector('input[name="choose"]')).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start session" })).toBeTruthy();
  });
});
