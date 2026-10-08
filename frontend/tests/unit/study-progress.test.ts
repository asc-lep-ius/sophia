import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StudyQuestion } from "../../src/lib/api/study";
import { cycleProgress, STUDY_PROGRESS } from "../../src/lib/study/progress";
import { load } from "../../src/routes/study/[sessionId]/+layout.server";
import { createLoadEvent } from "./support/request-event";

const page = vi.hoisted(() => ({
  route: { id: "/study/[sessionId]/predict" as string },
}));

vi.mock("$app/state", () => ({ page }));

const { default: SessionLayout } =
  await import("../../src/routes/study/[sessionId]/+layout.svelte");

const SESSION_ID = 7;

function card(id: string): StudyQuestion {
  return {
    id,
    kind: "open_response",
    topic: "Graphs",
    prompt: `Explain ${id}.`,
    difficulty: "explain",
    content_language: "en",
    translations: [],
    provenance: {
      origin: "lms",
      generated_by: "model",
      generator_ref: "test",
      generated_at: "2026-09-04T10:00:00Z",
      verified_by: null,
      verified_at: null,
      source_spans: [],
    },
    engagement_policy: {
      kind: "elaboration",
      required_event_types: ["prompt_shown"],
      min_elaboration_chars: 10,
      min_prompt_dwell_ms: 0,
    },
  };
}

const DECK = [card("anchor"), card("card-1"), card("card-2")];

function record(
  attemptedQuestionIds: string[],
  completedAt: string | null = null,
) {
  return {
    questions: DECK,
    attemptedQuestionIds,
    summary: { session: { topic: "Graphs", completed_at: completedAt } },
  };
}

function layoutData(
  attemptedQuestionIds: string[],
  completedAt: string | null = null,
) {
  return {
    ...record(attemptedQuestionIds, completedAt),
    sessionId: SESSION_ID,
  } as never;
}

function openOn(step: "predict" | "act" | "reflect", data: never) {
  page.route.id = `/study/[sessionId]/${step}`;
  return render(SessionLayout, { props: { data } });
}

function stepLink(name: RegExp): HTMLAnchorElement | null {
  return screen.queryByRole("link", { name }) as HTMLAnchorElement | null;
}

describe("cycleProgress", () => {
  it("opens nothing but the prediction on a fresh session", () => {
    const progress = cycleProgress(record([]) as never);

    expect([...progress.reachable]).toEqual(["predict"]);
    expect(progress.completed.size).toBe(0);
  });

  it("does not count a practice card as the pre-test", () => {
    const progress = cycleProgress(record(["card-1"]) as never);

    expect(progress.reachable.has("act")).toBe(false);
  });

  it("opens Work and Reflect together once the pre-test is on the server", () => {
    const progress = cycleProgress(record(["anchor"]) as never);

    expect([...progress.completed]).toEqual(["predict"]);
    expect(progress.reachable).toEqual(new Set(["predict", "act", "reflect"]));
  });

  it("marks Work done when every practice card has an attempt", () => {
    const progress = cycleProgress(
      record(["anchor", "card-1", "card-2"]) as never,
    );

    expect(progress.completed).toEqual(new Set(["predict", "act"]));
  });

  it("marks Reflect done when the session is closed, and keeps it reachable", () => {
    const progress = cycleProgress(
      record(["card-1"], "2026-09-04T10:45:00Z") as never,
    );

    expect(progress.completed.has("reflect")).toBe(true);
    expect(progress.reachable.has("reflect")).toBe(true);
    expect(progress.reachable.has("act")).toBe(false);
  });
});

describe("session stepper", () => {
  afterEach(() => {
    cleanup();
  });

  it("keeps Work and Reflect closed until the pre-test is answered", () => {
    openOn("predict", layoutData([]));

    expect(stepLink(/Predict/)).not.toBeNull();
    expect(stepLink(/Work/)).toBeNull();
    expect(stepLink(/Reflect/)).toBeNull();
    expect(screen.getByText("Work").tagName).toBe("SPAN");
  });

  // #108: Reflect was a link only once the learner was already on it, and
  // the deck-empty state was the one other way in.
  it("offers Reflect from Work without the deck being drained", () => {
    openOn("act", layoutData(["anchor"]));

    expect(stepLink(/Reflect/)?.getAttribute("href")).toBe(
      `/app/study/${SESSION_ID}/reflect`,
    );
    expect(stepLink(/Work/)?.getAttribute("aria-current")).toBe("step");
  });

  // #108: stepping back to Predict used to re-deaden Work, so the learner
  // could not step forward again by the same control.
  it("leaves Work and Reflect open after stepping back to Predict", () => {
    openOn("predict", layoutData(["anchor"]));

    expect(stepLink(/Predict/)?.getAttribute("aria-current")).toBe("step");
    expect(stepLink(/Work/)?.getAttribute("href")).toBe(
      `/app/study/${SESSION_ID}/act`,
    );
    expect(stepLink(/Reflect/)).not.toBeNull();
  });

  it("marks a finished step as completed, and only a finished one", () => {
    openOn("reflect", layoutData(["anchor"]));

    expect(stepLink(/Predict/)?.textContent).toMatch(/\(completed\)/);
    expect(stepLink(/Work/)?.textContent).not.toMatch(/\(completed\)/);
  });

  it("marks Work completed when the layout reloads on a deck drained in place", async () => {
    const { rerender } = openOn("act", layoutData(["anchor", "card-1"]));
    expect(stepLink(/Work/)?.textContent).not.toMatch(/\(completed\)/);

    await rerender({ data: layoutData(["anchor", "card-1", "card-2"]) });

    expect(stepLink(/Work/)?.textContent).toMatch(/\(completed\)/);
  });
});

describe("session layout load", () => {
  // The stepper is only as fresh as this load. SvelteKit re-runs a server
  // load when something it read has changed: before #108 it read nothing
  // that a step change touches, so a layout loaded on predict kept its
  // attempted ids until the learner reloaded the page.
  it("depends on the step it is loaded for and on the session's progress", async () => {
    let routeReads = 0;
    const depends = vi.fn();
    const fetch = vi.fn(async () => Response.json({ questions: [] }));
    const event = {
      ...createLoadEvent({
        fetch,
        url: `http://localhost/app/study/${SESSION_ID}/act`,
      }),
      depends,
      params: { sessionId: String(SESSION_ID) },
      route: {
        get id() {
          routeReads += 1;
          return "/study/[sessionId]/act";
        },
      },
    };

    await load(event as never);

    expect(routeReads).toBeGreaterThan(0);
    expect(depends).toHaveBeenCalledWith(STUDY_PROGRESS);
  });

  // #108: this load now re-runs on every step change, and a failed read of
  // the deck used to come back as an empty one — the stepper fell back to
  // Predict alone and the page offered to generate cards the session had.
  it("reports a failed read of the deck rather than calling it empty", async () => {
    const fetch = vi.fn(async (url: string) =>
      String(url).endsWith("/questions")
        ? new Response(null, { status: 503 })
        : Response.json({}),
    );
    const event = {
      ...createLoadEvent({
        fetch,
        url: `http://localhost/app/study/${SESSION_ID}/act`,
      }),
      depends: vi.fn(),
      params: { sessionId: String(SESSION_ID) },
      route: { id: "/study/[sessionId]/act" },
    };

    await expect(load(event as never)).rejects.toMatchObject({
      status: 502,
      body: { message: "study.api_unavailable" },
    });
  });
});
