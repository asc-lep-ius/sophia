import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  LearningEventInput,
  StudyPacing,
  StudyQuestion,
} from "../../src/lib/api/study";
import type { LearningEventDraft } from "../../src/lib/study/learningEvents";

// The act route holds an SSE connection open for the life of the card; jsdom
// has no EventSource, so it must be stubbed before the page mounts.
class FakeEventSource {
  static readonly CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  addEventListener(): void {
    // no-op: nothing in these tests emits a stream event
  }
  close(): void {
    // no-op
  }
}

vi.mock("../../src/lib/api/study", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../src/lib/api/study")>();
  return {
    ...actual,
    ingestLearningEvents: vi.fn(async () => undefined),
    submitAttempt: vi.fn(async () => ({}) as never),
    recordPrediction: vi.fn(async () => undefined),
  };
});

const { LearningEventBatcher } =
  await import("../../src/lib/study/learningEvents");
const { ingestLearningEvents } = await import("../../src/lib/api/study");
const { default: ActPage } =
  await import("../../src/routes/study/[sessionId]/act/+page.svelte");
const { default: PredictPage } =
  await import("../../src/routes/study/[sessionId]/predict/+page.svelte");

const pacing: StudyPacing = {
  reflection_min_seconds: 30,
  elaboration_min_chars: 10,
  prompt_min_dwell_ms: 5000,
};

function question(id: string): StudyQuestion {
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
      min_prompt_dwell_ms: 5000,
    },
  };
}

const summary = { session: { topic: "Graphs" } } as never;

function promptShownCount(spy: ReturnType<typeof vi.spyOn>): number {
  const calls = spy.mock.calls as unknown as [LearningEventDraft][];
  return calls.filter(([draft]) => draft.eventType === "prompt_shown").length;
}

describe("idle dwell clock vs prompt_shown", () => {
  let recordSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    recordSpy = vi.spyOn(LearningEventBatcher.prototype, "record");
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    cleanup();
    recordSpy.mockRestore();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  /**
   * StudyCard drives the store's dwell clock every 250ms so the reveal floor
   * can expire without a keystroke. Before this fix, recordPromptShown() read
   * that same clock, so the mounting $effect took a dependency on it: every
   * tick tore down and rebuilt the event batcher and emitted another
   * prompt_shown. This asserts the count stays at one across several ticks —
   * it would have caught the regression at 9 (1 mount + 8 ticks in 2s).
   */
  it("emits prompt_shown once on an idle /act card, not once per clock tick", async () => {
    render(ActPage, {
      data: {
        attemptedQuestionIds: [],
        csrfToken: "csrf",
        learningPathId: 12,
        pacing,
        questions: [question("anchor"), question("q-1")],
        requeuedQuestions: [],
        sessionId: 7,
        summary,
      } as never,
      form: null,
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(promptShownCount(recordSpy)).toBe(1);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(promptShownCount(recordSpy)).toBe(1);
  });

  it("emits prompt_shown once on an idle /predict card, not once per clock tick", async () => {
    render(PredictPage, {
      data: {
        attemptedQuestionIds: [],
        csrfToken: "csrf",
        learningPathId: 12,
        pacing,
        questions: [question("anchor")],
        sessionId: 7,
        summary,
      } as never,
      form: null,
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(promptShownCount(recordSpy)).toBe(1);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(promptShownCount(recordSpy)).toBe(1);
  });

  /**
   * The server's engagement policy takes the *highest* prompt_shown dwell_ms
   * it has seen for a question (src/sophia/services/engagement_policy.py) and
   * requires it to clear the pacing floor. The mount-time record above only
   * ever carries a near-zero dwell now that it no longer ticks — so without a
   * second, real-dwell prompt_shown at reveal time, every graded card would
   * be rejected 412. This pins that the reveal-time record carries enough.
   */
  it("carries a dwell that clears the floor once the card is revealed", async () => {
    render(ActPage, {
      data: {
        attemptedQuestionIds: [],
        csrfToken: "csrf",
        learningPathId: 12,
        pacing,
        questions: [question("anchor"), question("q-1")],
        requeuedQuestions: [],
        sessionId: 7,
        summary,
      } as never,
      form: null,
    });
    await vi.advanceTimersByTimeAsync(0);

    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: {
        value: "An answer long enough to clear the elaboration floor.",
      },
    });
    await vi.advanceTimersByTimeAsync(pacing.prompt_min_dwell_ms);
    await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    await fireEvent.click(screen.getByRole("button", { name: /Good/ }));

    // Past the outbox's cancel window, so the grade — and the event batch
    // ahead of it — has actually gone out.
    await vi.advanceTimersByTimeAsync(3_000);

    const sent = vi
      .mocked(ingestLearningEvents)
      .mock.calls.flatMap(([, events]) => events as LearningEventInput[]);
    const dwellsSeen = sent
      .filter((event) => event.event_type === "prompt_shown")
      .map((event) => Number(event.payload?.dwell_ms ?? 0));

    expect(Math.max(...dwellsSeen)).toBeGreaterThanOrEqual(
      pacing.prompt_min_dwell_ms,
    );
  });
});
