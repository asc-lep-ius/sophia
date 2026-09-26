import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StudyPacing, StudyQuestion } from "../../src/lib/api/study";
import { STUDY_PROGRESS } from "../../src/lib/study/progress";

/**
 * The cycle across its routes: what a step change keeps, and what finishing a
 * step without one tells the layout. Each route unmounts on a step change, so
 * unmounting and mounting again is the step change as far as a page can tell.
 */

class FakeEventSource {
  static readonly CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  addEventListener(): void {
    // nothing in these tests emits a stream event
  }
  close(): void {
    // nothing to release
  }
}

const navigation = vi.hoisted(() => ({
  goto: vi.fn(async () => undefined),
  invalidate: vi.fn(async () => undefined),
}));

vi.mock("$app/navigation", () => navigation);

vi.mock("../../src/lib/api/study", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../src/lib/api/study")>();
  return {
    ...actual,
    ingestLearningEvents: vi.fn(async () => undefined),
    submitAttempt: vi.fn(async () => ({}) as never),
    recordPrediction: vi.fn(async () => ({}) as never),
  };
});

const { default: ActPage } =
  await import("../../src/routes/study/[sessionId]/act/+page.svelte");
const { default: PredictPage } =
  await import("../../src/routes/study/[sessionId]/predict/+page.svelte");
const { default: ReflectPage } =
  await import("../../src/routes/study/[sessionId]/reflect/+page.svelte");

const SESSION_ID = 7;
const ANSWER = "Every path from source to sink crosses the cut.";

const pacing: StudyPacing = {
  reflection_min_seconds: 30,
  elaboration_min_chars: 10,
  prompt_min_dwell_ms: 0,
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
      min_prompt_dwell_ms: 0,
    },
  };
}

function pageData(attemptedQuestionIds: string[], cards = 2) {
  return {
    attemptedQuestionIds,
    csrfToken: "csrf",
    learningPathId: 12,
    pacing,
    questions: Array.from({ length: cards }, (_, index) =>
      question(index === 0 ? "anchor" : `card-${index}`),
    ),
    sessionId: SESSION_ID,
    summary: {
      session: { topic: "Graphs", completed_at: null },
      attempts: { pre_test: 0, practice: 0, post_test: 0 },
    },
  } as never;
}

function openAct(attemptedQuestionIds: string[], cards = 2) {
  return render(ActPage, {
    props: { data: pageData(attemptedQuestionIds, cards), form: null },
  });
}

function openPredict(attemptedQuestionIds: string[]) {
  return render(PredictPage, {
    props: { data: pageData(attemptedQuestionIds), form: null },
  });
}

/** On reflect with the post-test behind the learner, so the reflection is open. */
function openReflect() {
  const data = pageData(["anchor"]) as {
    summary: { attempts: { post_test: number } };
  };
  data.summary.attempts.post_test = 1;
  return render(ReflectPage, { props: { data: data as never } });
}

function answerField(): HTMLTextAreaElement {
  return screen.getByLabelText("Your answer") as HTMLTextAreaElement;
}

async function write(text: string): Promise<void> {
  await fireEvent.input(answerField(), { target: { value: text } });
}

describe("study cycle across step changes", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    navigation.invalidate.mockClear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  // #108: act -> predict -> act rebuilt the runtime, which seeded every card
  // with an empty answer.
  it("gives a practice card its answer back after the learner steps away", async () => {
    const first = openAct(["anchor"]);
    await write(ANSWER);
    first.unmount();

    openAct(["anchor"]);

    expect(answerField().value).toBe(ANSWER);
  });

  it("gives the pre-test its answer back after a reload of the predict route", async () => {
    const first = openPredict([]);
    await write(ANSWER);
    first.unmount();

    openPredict([]);

    expect(answerField().value).toBe(ANSWER);
  });

  // The acceptance's own path, predict -> act -> predict: the scale came back
  // unticked and Continue asked for a prediction the server already had.
  it("comes back to the prediction the learner made, with Continue open", async () => {
    const first = openPredict([]);
    await fireEvent.click(screen.getByRole("radio", { name: "Somewhat" }));
    await vi.advanceTimersByTimeAsync(0);
    first.unmount();

    openPredict(["anchor"]);

    expect(
      (screen.getByRole("radio", { name: "Somewhat" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "Start studying",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("gives the reflection its text back after the learner steps away", async () => {
    const first = openReflect();
    await fireEvent.input(screen.getByLabelText(/still feels unfinished/), {
      target: { value: ANSWER },
    });
    first.unmount();

    openReflect();

    expect(
      (screen.getByLabelText(/still feels unfinished/) as HTMLTextAreaElement)
        .value,
    ).toBe(ANSWER);
  });

  // Operator pre-mortem: a deck that drains without a navigation must still
  // reach the stepper. Nothing reloads the layout for it but the act route's
  // own invalidate(STUDY_PROGRESS), fired once the last grade has landed.
  it("reloads the session's progress once the last grade is on the server", async () => {
    openAct(["anchor"]);
    await write(ANSWER);
    await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    await fireEvent.click(screen.getByRole("button", { name: /Good/ }));

    expect(screen.getByText("No cards left in this session.")).toBeTruthy();
    expect(navigation.invalidate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(3000);

    expect(navigation.invalidate).toHaveBeenCalledTimes(1);
    expect(navigation.invalidate).toHaveBeenCalledWith(STUDY_PROGRESS);
  });

  it("does not reload progress for a deck that was already empty", async () => {
    openAct(["anchor", "card-1"]);

    await vi.advanceTimersByTimeAsync(3000);

    expect(screen.getByText("No cards left in this session.")).toBeTruthy();
    expect(navigation.invalidate).not.toHaveBeenCalled();
  });

  it("reloads the session's progress once the pre-test is on the server", async () => {
    openPredict([]);
    await fireEvent.click(screen.getByRole("radio", { name: "Somewhat" }));
    await write(ANSWER);
    await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    await fireEvent.click(screen.getByRole("button", { name: /Good/ }));

    expect(navigation.invalidate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(3000);

    expect(navigation.invalidate).toHaveBeenCalledWith(STUDY_PROGRESS);
  });
});
