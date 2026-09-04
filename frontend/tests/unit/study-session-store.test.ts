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
    // holdMs 0 dispatches immediately, which is what the submission tests
    // want; the cancel-window tests set their own hold.
    retry: { maxAttempts: 2, holdMs: 0, wait: async () => undefined },
    now: () => now,
    newId: () => `req-${(nextId += 1)}`,
  });

  return {
    store,
    submitted,
    advanceMs: (ms) => {
      now += ms;
      store.tick();
    },
    failEvery: (error) => {
      failure = error;
    },
  };
}

/** Let the outbox finish its retry loop before asserting on the rollback. */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 4; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
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

  it("measures dwell against the clock, not against when the timer last fired", () => {
    // The tick only exists to make the value reactive. On a loaded machine it
    // can be late, and reporting the last tick's timestamp as the dwell would
    // hold the reveal shut long after the learner had waited.
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0")],
      pacing,
      submit: async () => undefined,
      now: () => now,
    });

    now = 9000;

    expect(store.dwellMs).toBe(9000);
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

    expect(store.grade(3)).toBe(false);
    expect(submitted).toEqual([]);
  });

  it("advances optimistically on a grade and submits with a request id", async () => {
    const { store, submitted, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();

    store.grade(3);
    await settle();

    expect(submitted).toEqual([{ questionId: "q-0", requestId: "req-1" }]);
    expect(store.position).toBe(2);
    expect(store.state).toBe("prompt");
  });

  it("counts an Again grade into the again-later indicator", async () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();

    store.grade(1);

    expect(store.againLaterCount).toBe(1);
  });

  it("rolls the card back to its queue position when the server refuses", async () => {
    const { store, advanceMs, failEvery } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    failEvery(new TypeError("network down"));

    store.grade(4);
    await settle();

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

    store.grade(1);
    await settle();

    expect(store.againLaterCount).toBe(0);
  });

  it("undoes a grade that is still inside its cancel window", async () => {
    const submitted: { questionId: string; requestId: string }[] = [];
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0"), question("q-1")],
      pacing,
      submit: async (submission, requestId) => {
        submitted.push({ questionId: submission.questionId, requestId });
      },
      retry: { holdMs: 10_000 },
      now: () => now,
    });
    now = 6000;
    store.tick();
    elaborate(store);
    store.reveal();
    store.grade(4);

    expect(store.canUndo).toBe(true);
    expect(store.undo()).toBe(true);
    expect(store.position).toBe(1);
    expect(store.state).toBe("revealed");
    expect(store.error).toBeNull();

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(submitted).toEqual([]);
  });

  it("stops offering undo once the grade has gone", async () => {
    // The control goes quiet rather than staying enabled and apologising:
    // the harness dispatches immediately (holdMs 0), so there is nothing left
    // to cancel by the time the learner could press it.
    const { store, advanceMs } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);
    await settle();

    expect(store.canUndo).toBe(false);
    expect(store.undo()).toBe(false);
  });

  it("rewinds to the earliest rejected card when several fail at once", async () => {
    const { store, advanceMs, failEvery } = harness(3);
    failEvery(new TypeError("network down"));

    // Both grades go out before either answer comes back, which is the case
    // where a later rollback could overwrite an earlier one's restoration.
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);

    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);

    await settle();

    expect(store.position).toBe(1);
    expect(store.current?.question.id).toBe("q-0");
    expect(
      store.outboxEntries.filter((entry) => entry.status === "failed"),
    ).toHaveLength(2);
  });

  it("forgets a rejected grade once the card is graded again", async () => {
    // Left behind, the rejected entry keeps counting as unsaved and keeps
    // offering its queue position as somewhere a later rollback can rewind to
    // — landing the learner back on a card the server has since accepted.
    const { store, advanceMs, failEvery, submitted } = harness(4);

    failEvery(new TypeError("network down"));
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);
    await settle();
    expect(store.failedCount).toBe(1);

    failEvery(null);
    elaborate(store);
    store.grade(3);
    await settle();

    expect(store.failedCount).toBe(0);
    expect(submitted.map((entry) => entry.questionId)).toEqual(["q-0"]);
  });

  it("rewinds to the later card when an earlier failure was superseded", async () => {
    const { store, advanceMs, failEvery } = harness(4);

    failEvery(new TypeError("network down"));
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);
    await settle();

    failEvery(null);
    elaborate(store);
    store.grade(3);
    await settle();

    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);
    await settle();

    failEvery(new TypeError("network down"));
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    store.grade(3);
    await settle();

    // Card 3 failed; card 1's accepted re-grade must not drag the learner back.
    expect(store.current?.question.id).toBe("q-2");
  });

  it("lets the learner grade a rolled-back card again", async () => {
    const { store, advanceMs, failEvery } = harness();
    advanceMs(6000);
    elaborate(store);
    store.reveal();
    failEvery(new TypeError("network down"));
    store.grade(4);
    await settle();

    expect(store.state).toBe("rollback");
    expect(store.canGrade).toBe(true);
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
    store.tick();
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

    store.grade(2);
    await settle();

    expect(store.remaining).toBe(0);
    expect(store.current).toBeNull();
    expect(store.state).toBe("idle");
  });
});
