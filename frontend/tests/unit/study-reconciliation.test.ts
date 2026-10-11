import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SophiaApiError } from "../../src/lib/api/client";
import type {
  StudyPacing,
  StudyQuestion,
  StudyReconciliation,
  StudySessionSummary,
} from "../../src/lib/api/study";

/**
 * Reconciling the prediction with the result (#167): Reflect asks what
 * explains a gap once the numbers are open and closes the session only once
 * it is written; Predict shows that line back the next time, and takes a
 * "because…" of its own.
 */

const navigation = vi.hoisted(() => ({
  goto: vi.fn(async () => undefined),
  invalidate: vi.fn(async () => undefined),
}));

vi.mock("$app/navigation", () => navigation);

const api = vi.hoisted(() => ({
  calls: [] as string[],
  summary: null as unknown,
}));

vi.mock("../../src/lib/api/study", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../src/lib/api/study")>();
  return {
    ...actual,
    ingestLearningEvents: vi.fn(async () => undefined),
    submitAttempt: vi.fn(async () => ({}) as never),
    recordPrediction: vi.fn(async () => {
      api.calls.push("recordPrediction");
    }),
    savePredictionReason: vi.fn(async () => {
      api.calls.push("savePredictionReason");
    }),
    saveReflection: vi.fn(async () => {
      api.calls.push("saveReflection");
    }),
    saveReconciliation: vi.fn(async () => {
      api.calls.push("saveReconciliation");
    }),
    completeSession: vi.fn(async () => {
      api.calls.push("completeSession");
      return {} as never;
    }),
    loadSessionSummary: vi.fn(async () => api.summary),
  };
});

const study = await import("../../src/lib/api/study");
const { default: PredictPage } =
  await import("../../src/routes/study/[sessionId]/predict/+page.svelte");
const { default: ReflectPage } =
  await import("../../src/routes/study/[sessionId]/reflect/+page.svelte");

const SESSION_ID = 7;
const GAP = "I could recite the definition but never traced a cut by hand.";

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

function reconciliation(
  overrides: Partial<StudyReconciliation> = {},
): StudyReconciliation {
  return {
    id: 1,
    session_id: 3,
    learning_path_id: 12,
    predicted: 1,
    measured: 0,
    band: "overconfident",
    reconciliation_text: GAP,
    created_at: "2026-10-10T10:00:00+00:00",
    ...overrides,
  };
}

/** A post-tested session whose prediction of "Very well" met a score of 0. */
function summary(
  overrides: Partial<StudySessionSummary> = {},
): StudySessionSummary {
  return {
    session: {
      id: SESSION_ID,
      learning_path_id: 12,
      topic: "Graphs",
      pre_test_score: 0,
      post_test_score: 0,
      started_at: "2026-10-11T10:00:00+00:00",
      completed_at: null,
      improvement: 0,
    },
    attempts: { pre_test: 1, practice: 2, post_test: 1 },
    practice_score: 0,
    predicted: 1,
    prediction_reason: null,
    measured: 0,
    calibration_delta: -1,
    band: "overconfident",
    legacy_scored: false,
    reflected: true,
    reconciliation_required: true,
    reconciliation: null,
    previous_reconciliation: null,
    ...overrides,
  };
}

function pageData(sessionSummary: StudySessionSummary, attempted: string[]) {
  return {
    attemptedQuestionIds: attempted,
    csrfToken: "csrf",
    learningPathId: 12,
    pacing,
    questions: [question("anchor"), question("card-1")],
    requeuedQuestions: [],
    sessionId: SESSION_ID,
    summary: sessionSummary,
  } as never;
}

function openReflect(sessionSummary: StudySessionSummary) {
  return render(ReflectPage, {
    props: { data: pageData(sessionSummary, ["anchor", "card-1"]) },
  });
}

function openPredict(sessionSummary: StudySessionSummary) {
  return render(PredictPage, {
    props: { data: pageData(sessionSummary, []), form: null },
  });
}

function finishButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: "Finish session",
  }) as HTMLButtonElement;
}

function reconcileField(): HTMLTextAreaElement {
  return screen.getByLabelText(
    /What explains the gap\?/,
  ) as HTMLTextAreaElement;
}

beforeEach(() => {
  vi.useFakeTimers();
  api.calls = [];
  api.summary = null;
  navigation.goto.mockClear();
  vi.mocked(study.completeSession).mockClear();
  vi.mocked(study.recordPrediction).mockClear();
  vi.mocked(study.savePredictionReason).mockClear();
  vi.mocked(study.saveReconciliation).mockClear();
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Reflect once the results open", () => {
  it("opens the results on the reflection without closing the session", async () => {
    api.summary = summary();
    openReflect(summary({ reflected: false }));
    await fireEvent.input(screen.getByLabelText(/still feels unfinished/), {
      target: { value: "The cut argument took me a while." },
    });
    await vi.advanceTimersByTimeAsync(30_000);

    await fireEvent.click(
      screen.getByRole("button", { name: "Show my results" }),
    );
    await vi.advanceTimersByTimeAsync(0);

    expect(api.calls).toEqual(["saveReflection"]);
    expect(reconcileField().labels?.[0]?.textContent?.trim()).toBe(
      "You predicted 100% and scored 0%. What explains the gap?",
    );
    expect(finishButton().disabled).toBe(true);
  });

  it("finishes a missed prediction only once the gap is explained", async () => {
    openReflect(summary());

    expect(finishButton().disabled).toBe(true);
    expect(
      screen.getByText(
        "Write one line on what explains the gap to finish the session.",
      ),
    ).toBeTruthy();

    await fireEvent.input(reconcileField(), { target: { value: GAP } });
    await fireEvent.click(finishButton());
    await vi.advanceTimersByTimeAsync(0);

    expect(api.calls).toEqual(["saveReconciliation", "completeSession"]);
    expect(study.saveReconciliation).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: SESSION_ID }),
      expect.objectContaining({ reconciliationText: GAP }),
    );
    expect(navigation.goto).toHaveBeenCalledWith("/app/study");
  });

  it("offers the prompt on a matched prediction but finishes without it", async () => {
    openReflect(
      summary({
        measured: 1,
        calibration_delta: 0,
        band: "well_calibrated",
        reconciliation_required: false,
      }),
    );

    expect(
      screen.getByLabelText(
        "You predicted 100% and scored 100%. If you like, note what made the prediction hold.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Optional. You can finish without it."),
    ).toBeTruthy();
    expect(finishButton().disabled).toBe(false);

    await fireEvent.click(finishButton());
    await vi.advanceTimersByTimeAsync(0);

    expect(api.calls).toEqual(["completeSession"]);
  });

  it("shows the reason given with the prediction beside the results", () => {
    openReflect(summary({ prediction_reason: "I did the lab last week." }));

    expect(screen.getByTestId("prediction-reason").textContent?.trim()).toBe(
      "Your reason: I did the lab last week.",
    );
  });

  it("says why when the server refuses to close the session", async () => {
    vi.mocked(study.completeSession).mockRejectedValueOnce(
      new SophiaApiError({
        status: 412,
        detail: {
          code: "engagement.policy_unmet",
          params: { required: "reconciliation", band: "overconfident" },
        },
      }),
    );
    openReflect(summary());
    await fireEvent.input(reconcileField(), { target: { value: GAP } });

    await fireEvent.click(finishButton());
    await vi.advanceTimersByTimeAsync(0);

    expect(screen.getByRole("alert").textContent?.trim()).toBe(
      "The session finishes once you have written what explains the gap.",
    );
    expect(navigation.goto).not.toHaveBeenCalled();
  });
});

describe("Predict after a reconciled session", () => {
  it("shows the last reconciliation above the rating", () => {
    openPredict(summary({ previous_reconciliation: reconciliation() }));

    const previous = screen.getByTestId("previous-reconciliation");
    const scale = screen.getByRole("radio", { name: "Very well" });
    expect(previous.textContent?.trim()).toBe(GAP);
    expect(
      screen.getByText(
        "You predicted 100% and scored 0%. Afterwards you wrote:",
      ),
    ).toBeTruthy();
    expect(
      previous.compareDocumentPosition(scale) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows nothing to read back on a first session", () => {
    openPredict(summary());

    expect(screen.queryByTestId("previous-reconciliation")).toBeNull();
  });

  it("sends a reason written first along with the rating", async () => {
    openPredict(summary());
    await fireEvent.input(screen.getByLabelText(/Because/), {
      target: { value: "I did the lab last week." },
    });

    await fireEvent.click(screen.getByRole("radio", { name: "Very well" }));
    await vi.advanceTimersByTimeAsync(0);

    expect(study.recordPrediction).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        rating: 5,
        reason: "I did the lab last week.",
      }),
    );
  });

  it("puts a reason written after the rating on the saved prediction", async () => {
    openPredict(summary());
    await fireEvent.click(screen.getByRole("radio", { name: "Very well" }));
    await vi.advanceTimersByTimeAsync(0);
    const field = screen.getByLabelText(/Because/);

    await fireEvent.input(field, {
      target: { value: "I did the lab last week." },
    });
    await fireEvent.change(field);
    await vi.advanceTimersByTimeAsync(0);

    expect(study.recordPrediction).toHaveBeenCalledTimes(1);
    expect(study.savePredictionReason).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: SESSION_ID }),
      "I did the lab last week.",
    );
  });
});
