import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StudyPacing, StudyQuestion } from "../../src/lib/api/study";

type Call = { kind: "events" | "attempt"; keepalive: boolean | undefined };

const calls: Call[] = [];

vi.mock("../../src/lib/api/study", () => ({
  ingestLearningEvents: async (
    _context: unknown,
    _events: unknown,
    options: { keepalive?: boolean } = {},
  ) => {
    calls.push({ kind: "events", keepalive: options.keepalive });
  },
  submitAttempt: async (
    _context: unknown,
    _input: unknown,
    options: { keepalive?: boolean } = {},
  ) => {
    calls.push({ kind: "attempt", keepalive: options.keepalive });
    return {};
  },
  isRetryableFailure: () => false,
}));

const { createStudyRuntime } = await import("../../src/lib/study/runtime");

const pacing: StudyPacing = {
  reflection_min_seconds: 30,
  elaboration_min_chars: 10,
  prompt_min_dwell_ms: 0,
};

const question: StudyQuestion = {
  id: "q-1",
  kind: "open_response",
  topic: "Graphs",
  prompt: "Explain a minimum cut.",
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

function runtimeFor() {
  return createStudyRuntime({
    csrfToken: "csrf",
    learningPathId: 12,
    sessionId: 7,
    questions: [question],
    pacing,
    phase: "practice",
  });
}

async function settle(): Promise<void> {
  for (let turn = 0; turn < 4; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

describe("study runtime unload path", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("sends the trace and the held grade in a way that outlives the page", async () => {
    // Both matter: the attempt's own submission awaits the event flush, so an
    // events POST the browser cancels on unload takes the attempt with it.
    const runtime = runtimeFor();
    runtime.store.recordPromptShown();
    runtime.store.setAnswer("An answer long enough to reveal with.");
    runtime.store.reveal();
    runtime.store.grade(3);

    runtime.flushOnUnload();
    await settle();

    expect(calls.map((call) => call.kind)).toEqual(["events", "attempt"]);
    expect(calls.every((call) => call.keepalive === true)).toBe(true);
  });

  it("stops using the unload path when the page comes back from the bfcache", async () => {
    const runtime = runtimeFor();
    runtime.flushOnUnload();
    await settle();
    runtime.resumeFromUnload();

    runtime.store.recordPromptShown();
    runtime.store.setAnswer("An answer long enough to reveal with.");
    runtime.store.reveal();
    runtime.store.grade(3);
    await runtime.events.flushNow();

    expect(calls.at(-1)?.keepalive).toBe(false);
  });

  it("does not post an empty batch on teardown", async () => {
    const runtime = runtimeFor();

    runtime.destroy();
    await settle();

    expect(calls).toEqual([]);
  });
});
