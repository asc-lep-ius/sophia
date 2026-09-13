import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchController } from "../../src/lib/search/controller.svelte";
import type { SearchResult } from "../../src/lib/search/results";

const DEBOUNCE_MS = 50;

function result(id: string): SearchResult {
  return {
    chunk_text: id,
    content_item_id: id,
    end_time: 10,
    score: 0.5,
    source: "transcript",
    start_time: 0,
    title: id,
  };
}

/** A run whose settling this test decides, so orderings can be forced. */
function deferredRun() {
  const calls: {
    query: string;
    signal: AbortSignal;
    settle: (results: SearchResult[]) => void;
    reject: (error: unknown) => void;
  }[] = [];

  const run = (query: string, signal: AbortSignal) =>
    new Promise<SearchResult[]>((settle, reject) => {
      calls.push({ query, reject, settle, signal });
    });

  return { calls, run };
}

describe("search controller", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends nothing until typing stops", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    for (const query of ["g", "gr", "gra", "grap", "graph"]) {
      controller.setQuery(query);
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS / 5);
    }
    expect(calls).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(calls.map((call) => call.query)).toEqual(["graph"]);
  });

  it("does not search a query too short to mean anything", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("g");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS * 2);

    expect(calls).toHaveLength(0);
    expect(controller.status).toBe("idle");
  });

  it("aborts a run that a newer query has replaced", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    controller.setQuery("graphen");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(calls).toHaveLength(2);
    expect(calls[0]?.signal.aborted).toBe(true);
    expect(calls[1]?.signal.aborted).toBe(false);
  });

  /**
   * The failure a debounce alone does not prevent. Abort is a request to stop,
   * not a guarantee the response never lands, so a slow early search can
   * settle after the one that replaced it. Letting it write would rewind the
   * learner's results to a query they finished typing seconds ago.
   */
  it("ignores an older run that settles after a newer one", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    controller.setQuery("graphen");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    calls[1]?.settle([result("new")]);
    await vi.advanceTimersByTimeAsync(0);
    calls[0]?.settle([result("stale")]);
    await vi.advanceTimersByTimeAsync(0);

    expect(controller.results.map((entry) => entry.title)).toEqual(["new"]);
    expect(controller.submitted).toBe("graphen");
  });

  it("does not report an abandoned run as a failure", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    controller.setQuery("graphen");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    calls[0]?.reject(new Error("aborted"));
    await vi.advanceTimersByTimeAsync(0);

    expect(controller.status).toBe("loading");
  });

  it("reports a failure the learner can act on", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    calls[0]?.reject(new Error("boom"));
    await vi.advanceTimersByTimeAsync(0);

    expect(controller.status).toBe("error");
    expect(controller.results).toEqual([]);
  });

  it("separates a search that found nothing from one never made", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    expect(controller.isEmpty).toBe(false);

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    calls[0]?.settle([]);
    await vi.advanceTimersByTimeAsync(0);

    expect(controller.isEmpty).toBe(true);
  });

  it("clears the results and cancels the run when the box is emptied", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    calls[0]?.settle([result("a")]);
    await vi.advanceTimersByTimeAsync(0);

    controller.setQuery("");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS * 2);

    expect(controller.status).toBe("idle");
    expect(controller.results).toEqual([]);
    expect(controller.submitted).toBe("");
    expect(calls).toHaveLength(1);
  });

  it("searches immediately when the learner submits", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    controller.submit();

    expect(calls.map((call) => call.query)).toEqual(["graph"]);

    // The scheduled run was cancelled rather than left to fire as a second one.
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS * 2);

    expect(calls).toHaveLength(1);
  });

  it("abandons a pending and an in-flight run when the page goes away", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("graph");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    controller.setQuery("graphen");
    controller.dispose();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS * 2);

    expect(calls).toHaveLength(1);
    expect(calls[0]?.signal.aborted).toBe(true);
  });

  it("trims the query it sends, never the one the learner sees", async () => {
    const { calls, run } = deferredRun();
    const controller = new SearchController({ debounceMs: DEBOUNCE_MS, run });

    controller.setQuery("  graph  ");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(calls[0]?.query).toBe("graph");
    expect(controller.query).toBe("  graph  ");
  });
});
