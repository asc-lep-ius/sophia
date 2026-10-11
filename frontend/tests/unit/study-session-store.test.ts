import { describe, expect, it, vi } from "vitest";

import type { StudyPacing, StudyQuestion } from "../../src/lib/api/study";
import { sessionDrafts } from "../../src/lib/study/drafts";
import {
  AGAIN_REASK_LIMIT,
  StudySessionStore,
  type Confidence,
  type Grade,
  type GradeSubmission,
} from "../../src/lib/study/session.svelte";

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

/** Press Reveal and say how sure: the two steps every reveal now takes. */
function reveal(store: StudySessionStore, confidence: Confidence = 3): boolean {
  store.askConfidence();
  return store.reveal(confidence);
}

describe("study session store", () => {
  it("starts in prompt and refuses to reveal before the elaboration floor", () => {
    const { store, advanceMs } = harness();
    advanceMs(6000);

    expect(store.state).toBe("prompt");
    store.setAnswer("short");
    expect(store.canReveal).toBe(false);
    expect(store.askConfidence()).toBe(false);
    expect(store.reveal(3)).toBe(false);
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
    reveal(store);

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
    reveal(store);

    store.grade(1);

    expect(store.againLaterCount).toBe(1);
  });

  it("rolls the card back to its queue position when the server refuses", async () => {
    const { store, advanceMs, failEvery } = harness();
    advanceMs(6000);
    elaborate(store);
    reveal(store);
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
    reveal(store);
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
    reveal(store);
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
    reveal(store);
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
    reveal(store);
    store.grade(3);

    advanceMs(6000);
    elaborate(store);
    reveal(store);
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
    reveal(store);
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
    reveal(store);
    store.grade(3);
    await settle();

    failEvery(null);
    elaborate(store);
    store.grade(3);
    await settle();

    advanceMs(6000);
    elaborate(store);
    reveal(store);
    store.grade(3);
    await settle();

    failEvery(new TypeError("network down"));
    advanceMs(6000);
    elaborate(store);
    reveal(store);
    store.grade(3);
    await settle();

    // Card 3 failed; card 1's accepted re-grade must not drag the learner back.
    expect(store.current?.question.id).toBe("q-2");
  });

  it("lets the learner grade a rolled-back card again", async () => {
    const { store, advanceMs, failEvery } = harness();
    advanceMs(6000);
    elaborate(store);
    reveal(store);
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
    reveal(store);

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
    reveal(store);

    expect(record.mock.calls.map(([draft]) => draft.eventType)).toEqual([
      "prompt_shown",
      "elaboration_written",
      "prompt_shown",
      "answer_revealed",
    ]);
  });

  it("ends the queue rather than wrapping around", async () => {
    const { store, advanceMs } = harness(1);
    advanceMs(6000);
    elaborate(store);
    reveal(store);

    store.grade(2);
    await settle();

    expect(store.remaining).toBe(0);
    expect(store.current).toBeNull();
    expect(store.state).toBe("idle");
  });
});

describe("confidence before the reveal", () => {
  function recordingStore(record = vi.fn()) {
    const sent: GradeSubmission[] = [];
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0"), question("q-1")],
      pacing,
      learningEvents: { record },
      submit: async (submission) => {
        sent.push(submission);
      },
      retry: { maxAttempts: 1, holdMs: 0, wait: async () => undefined },
      now: () => now,
    });
    const advanceMs = (ms: number) => {
      now += ms;
      store.tick();
    };
    return {
      store,
      sent,
      record,
      advanceMs,
      ready: () => {
        advanceMs(6000);
        elaborate(store);
      },
    };
  }

  it("asks how sure the learner is when they press Reveal, and shows nothing yet", () => {
    const { store, record, ready } = recordingStore();
    ready();

    expect(store.askConfidence()).toBe(true);

    expect(store.state).toBe("confidence");
    expect(store.askingConfidence).toBe(true);
    expect(store.current?.revealed).toBe(false);
    expect(store.canGrade).toBe(false);
    expect(record.mock.calls.map(([draft]) => draft.eventType)).not.toContain(
      "answer_revealed",
    );
  });

  it("never reveals a card it has not asked about", () => {
    const { store, ready } = recordingStore();
    ready();

    expect(store.reveal(4)).toBe(false);
    expect(store.current?.revealed).toBe(false);
  });

  it("reveals once a confidence is chosen and sends it as the attempt's", async () => {
    const { store, sent, record, ready } = recordingStore();
    ready();
    store.askConfidence();

    expect(store.reveal(4)).toBe(true);
    expect(store.current?.confidence).toBe(4);
    expect(record.mock.calls.at(-1)?.[0].eventType).toBe("answer_revealed");

    store.grade(3);
    await settle();

    expect(sent.map((submission) => submission.confidence)).toEqual([4]);
  });

  it("asks again on every card, a re-ask included", async () => {
    const { store, sent, ready } = recordingStore();
    for (const confidence of [5, 2] as const) {
      ready();
      reveal(store, confidence);
      store.grade(1);
    }
    ready();

    expect(store.current?.question.id).toBe("q-0");
    expect(store.current?.retry).toBe(1);
    expect(store.current?.confidence).toBeNull();
    expect(store.reveal(3)).toBe(false);

    reveal(store, 3);
    store.grade(3);
    await settle();

    expect(sent.map((submission) => submission.confidence)).toEqual([5, 2, 3]);
  });

  it("keeps the confidence through an undo, since the answer has been seen", async () => {
    const sent: GradeSubmission[] = [];
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0"), question("q-1")],
      pacing,
      submit: async (submission) => {
        sent.push(submission);
      },
      retry: { maxAttempts: 1, holdMs: 5000, wait: async () => undefined },
      now: () => now,
    });
    now = 6000;
    store.tick();
    elaborate(store);
    reveal(store, 2);
    store.grade(4);

    expect(store.undo()).toBe(true);
    expect(store.state).toBe("revealed");
    store.grade(2);
    store.flushGrades();
    await settle();

    expect(sent.map((submission) => submission.confidence)).toEqual([2]);
  });

  it("is still asking after a pause, once the dwell clock has run again", () => {
    // The reveal's prompt_shown carries the dwell the server checks, and a
    // resume restarts it: revealing straight after would earn a 412.
    const { store, ready, advanceMs } = recordingStore();
    ready();
    store.askConfidence();

    store.pause();
    expect(store.askingConfidence).toBe(true);
    expect(store.reveal(3)).toBe(false);

    store.resume();
    expect(store.state).toBe("confidence");
    expect(store.canChooseConfidence).toBe(false);

    advanceMs(6000);
    expect(store.reveal(3)).toBe(true);
  });
});

/** Answer the card in front of the learner and grade it; returns its id. */
function work(
  { store, advanceMs }: Pick<StoreHarness, "store" | "advanceMs">,
  rating: Grade,
): string | undefined {
  const id = store.current?.question.id;
  advanceMs(6000);
  elaborate(store);
  reveal(store);
  store.grade(rating);
  return id;
}

/** The ids of every card presented, grading each with `rating`, to the end. */
function workToTheEnd(h: StoreHarness, rating: Grade): string[] {
  const seen: string[] = [];
  // Bounded, so a queue that never drains fails the test instead of hanging it.
  for (let step = 0; step < 20 && h.store.current; step += 1) {
    seen.push(work(h, rating) ?? "");
  }
  return seen;
}

describe("a card graded Again", () => {
  it("comes back after the other cards, empty, and holds the queue open until answered", async () => {
    const h = harness(4);
    work(h, 3);
    work(h, 1);
    work(h, 3);
    work(h, 3);

    expect(h.store.current?.question.id).toBe("q-1");
    expect(h.store.answer).toBe("");
    expect(h.store.state).toBe("prompt");
    expect(h.store.remaining).toBe(1);

    work(h, 3);
    await settle();

    expect(h.store.remaining).toBe(0);
    expect(h.store.state).toBe("idle");
    // The re-ask is a second attempt under its own request id.
    expect(h.submitted.map((entry) => entry.questionId)).toEqual([
      "q-0",
      "q-1",
      "q-2",
      "q-3",
      "q-1",
    ]);
    expect(new Set(h.submitted.map((entry) => entry.requestId)).size).toBe(5);
  });

  it("is re-presented at most twice in one session", () => {
    const h = harness(2);

    const seen = workToTheEnd(h, 1);

    expect(AGAIN_REASK_LIMIT).toBe(2);
    expect(seen).toEqual(["q-0", "q-1", "q-0", "q-1", "q-0", "q-1"]);
    expect(h.store.remaining).toBe(0);
  });

  it("does not come straight back while another card remains", () => {
    const h = harness(3);
    work(h, 1);
    work(h, 3);

    // The last unanswered card: q-0's re-ask is still between it and its own.
    work(h, 1);

    expect(h.store.current?.question.id).toBe("q-0");
    work(h, 3);
    expect(h.store.current?.question.id).toBe("q-2");
  });

  it("comes straight back when nothing else remains", () => {
    const h = harness(1);

    work(h, 1);

    expect(h.store.current?.question.id).toBe("q-0");
    expect(h.store.answer).toBe("");
  });

  it("counts only re-asks still to come as again later", () => {
    const h = harness(2);
    work(h, 1);
    expect(h.store.againLaterCount).toBe(1);

    work(h, 3);
    // On the re-ask itself: it is now, not later.
    expect(h.store.current?.question.id).toBe("q-0");
    expect(h.store.againLaterCount).toBe(0);
  });

  it("is not re-asked on the pre-test, which is a measurement", () => {
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("anchor")],
      pacing,
      phase: "pre_test",
      submit: async () => undefined,
      retry: { holdMs: 0, wait: async () => undefined },
      now: () => now,
    });
    const advanceMs = (ms: number) => {
      now += ms;
      store.tick();
    };

    expect(work({ store, advanceMs }, 1)).toBe("anchor");

    expect(store.remaining).toBe(0);
    expect(store.againLaterCount).toBe(0);
  });

  it("is taken back with an undone grade", () => {
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0"), question("q-1")],
      pacing,
      submit: async () => undefined,
      retry: { holdMs: 10_000 },
      now: () => now,
    });
    const advanceMs = (ms: number) => {
      now += ms;
      store.tick();
    };
    work({ store, advanceMs }, 1);
    expect(store.total).toBe(3);

    expect(store.undo()).toBe(true);

    expect(store.current?.question.id).toBe("q-0");
    expect(store.total).toBe(2);
    expect(store.againLaterCount).toBe(0);
  });

  it("is taken back with an undone grade that had already called it in", () => {
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0")],
      pacing,
      submit: async () => undefined,
      retry: { holdMs: 10_000 },
      now: () => now,
    });
    const advanceMs = (ms: number) => {
      now += ms;
      store.tick();
    };
    work({ store, advanceMs }, 1);
    expect(store.total).toBe(2);

    store.undo();
    store.grade(3);

    expect(store.total).toBe(1);
    expect(store.remaining).toBe(0);
  });

  it("is taken back when the server refuses the grade", async () => {
    const h = harness(2);
    h.failEvery(new TypeError("network down"));

    work(h, 1);
    await settle();

    expect(h.store.current?.question.id).toBe("q-0");
    expect(h.store.total).toBe(2);
  });

  it("keeps the first answer's draft away from the re-ask", () => {
    const storage = new Map<string, string>();
    const drafts = sessionDrafts(7, "practice", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => void storage.set(key, value),
      removeItem: (key: string) => void storage.delete(key),
    } as Storage);
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-0")],
      pacing,
      drafts,
      submit: async () => undefined,
      // Held: the first answer's draft is still waiting for the server.
      retry: { holdMs: 10_000 },
      now: () => now,
    });

    work(
      {
        store,
        advanceMs: (ms) => {
          now += ms;
          store.tick();
        },
      },
      1,
    );

    expect(drafts.read("q-0")).not.toBeNull();
    expect(store.answer).toBe("");
  });
});

describe("a session resumed with a card still owed a re-ask", () => {
  function resumed(retry: number) {
    let now = 0;
    const store = new StudySessionStore({
      questions: [question("q-2")],
      requeued: [{ question: question("q-1"), retry }],
      pacing,
      submit: async () => undefined,
      retry: { holdMs: 0, wait: async () => undefined },
      now: () => now,
    });
    const advanceMs = (ms: number) => {
      now += ms;
      store.tick();
    };
    return { store, advanceMs };
  }

  it("presents it again after the cards still unanswered", () => {
    const h = resumed(1);
    expect(h.store.remaining).toBe(2);
    expect(h.store.againLaterCount).toBe(1);

    work(h, 3);

    expect(h.store.current?.question.id).toBe("q-1");
    expect(h.store.answer).toBe("");
  });

  it("opens on it when it is all that is left", () => {
    const store = new StudySessionStore({
      questions: [],
      requeued: [{ question: question("q-1"), retry: 1 }],
      pacing,
      submit: async () => undefined,
    });

    expect(store.state).toBe("prompt");
    expect(store.current?.question.id).toBe("q-1");
  });

  it("keeps counting towards the cap across the reload", () => {
    const h = resumed(AGAIN_REASK_LIMIT);
    work(h, 3);

    work(h, 1);

    expect(h.store.remaining).toBe(0);
  });
});
