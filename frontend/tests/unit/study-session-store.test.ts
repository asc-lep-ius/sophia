import { describe, expect, it, vi } from "vitest";

import type { StudyPacing, StudyQuestion } from "../../src/lib/api/study";
import { StudySessionStore } from "../../src/lib/study/session.svelte";

const pacing: StudyPacing = {
  reflection_min_seconds: 30,
  elaboration_min_chars: 10,
  prompt_min_dwell_ms: 5000,
};

function question(id: string, minChars = 10): StudyQuestion {
  return {
    id,
    kind: "open_response",
    topic: "Graphs",
    prompt: `Explain ${id}`,
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
      min_elaboration_chars: minChars,
      min_prompt_dwell_ms: 5000,
    },
  };
}

type StoreHarness = {
  store: StudySessionStore;
  submitted: { questionId: string; requestId: string }[];
  advanceMs: (ms: number) => void;
  failEvery: (error: unknown) => void;
};

function harness(questionCount = 2): StoreHarness {
  let now = 0;
  let nextId = 0;
  let failure: unknown = null;
  const submitted: { questionId: string; requestId: string }[] = [];

  const store = new StudySessionStore({
    questions: Array.from({ length: questionCount }, (_, index) =>
      question(`q-${index}`),
    ),
    pacing,
    submit: async (submission, requestId) => {
      if (failure) {
        throw failure;
      }
      submitted.push({ questionId: submission.questionId, requestId });
    },
    retry: { maxAttempts: 2, wait: async () => undefined },
    now: () => now,
    newId: () => `req-${(nextId += 1)}`,
  });

  return {
    store,
    submitted,
    advanceMs: (ms) => {
      now += ms;
    },
    failEvery: (error) => {
      failure = error;
    },
  };
}

function elaborate(store: StudySessionStore): void {
  store.setAnswer("An answer long enough to satisfy the elaboration floor.");
}

describe("study session store", () => {
  it("starts in prompt and refuses to reveal before the elaboration floor", () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);

    expect(store.state).toBe("prompt");
    store.setAnswer("short");
    expect(store.canReveal).toBe(false);
    expect(store.reveal()).toBe(false);
    expect(store.state).toBe("prompt");
  });

  it("refuses to reveal before the prompt dwell floor even with an answer", () => {
    const { store, advanceMs } = harness();
    advanceMs(1000);
    elaborate(store);

    expect(store.canReveal).toBe(false);
  });

  it("cannot jump from prompt to a grade without revealing", async () => {
    const { store, submitted, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);

    expect(await store.grade(3)).toBe(false);
    expect(submitted).toEqual([]);
  });

  it("advances optimistically on a grade and submits with a request id", async () => {
    const { store, submitted, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();

    await store.grade(3);

    expect(submitted).toEqual([{ questionId: "q-0", requestId: "req-1" }]);
    expect(store.position).toBe(2);
    expect(store.state).toBe("prompt");
  });

  it("counts an Again grade into the again-later indicator", async () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();

    await store.grade(1);

    expect(store.againLaterCount).toBe(1);
  });

  it("rolls the card back to its queue position when the server refuses", async () => {
    const { store, advanceMs, failEvery } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    failEvery(new TypeError("network down"));

    await store.grade(4);

    expect(store.state).toBe("rollback");
    expect(store.error).toBe("study.grade_rejected");
    expect(store.position).toBe(1);
    expect(store.current?.question.id).toBe("q-0");
  });

  it("keeps the optimistic state from becoming the truth after a failure", async () => {
    const { store, advanceMs, failEvery } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    failEvery(new TypeError("network down"));

    await store.grade(1);

    expect(store.againLaterCount).toBe(0);
  });

  it("refuses to undo a grade the server already accepted", async () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    await store.grade(3);

    expect(store.undo()).toBe(false);
    expect(store.error).toBe("study.undo_already_committed");
  });

  it("pauses to the state it resumes into", () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();

    store.pause();
    expect(store.state).toBe("paused");
    expect(store.paused).toBe(true);

    store.resume();
    expect(store.state).toBe("revealed");
  });

  it("restarts the dwell clock on resume so a pause is not engagement", () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.pause();
    advanceMs(60_000);
    store.resume();

    expect(store.dwellMs).toBe(0);
    expect(store.canReveal).toBe(false);
  });

  it("ignores answer edits while paused", () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);
    store.pause();
    store.setAnswer("typed while paused");

    expect(store.answer).toBe("");
  });

  it("records the learner's process trace as the card is worked", () => {
    const record = vi.fn();
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0")],
      pacing,
      learningEvents: { record },
      submit: async () => undefined,
      now: () => now,
    });

    now = 6000;
    store.recordPromptShown();
    elaborate(store);
    store.reveal();

    expect(record.mock.calls.map(([draft]) => draft.eventType)).toEqual([
      "prompt_shown",
      "elaboration_written",
      "answer_revealed",
    ]);
  });

  it("ends the queue rather than wrapping around", async () => {
    const { store, advanceMs } = harness(1);
    advanceMs(6000);
    elaborate(store);
    store.reveal();

    await store.grade(2);

    expect(store.remaining).toBe(0);
    expect(store.current).toBeNull();
    expect(store.state).toBe("idle");
  });
});
