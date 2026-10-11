import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import type { StudyPacing, StudyQuestion } from "../../src/lib/api/study";
import StudyCard from "../../src/lib/components/study/StudyCard.svelte";
import { StudySessionStore } from "../../src/lib/study/session.svelte";

const pacing: StudyPacing = {
  reflection_min_seconds: 30,
  elaboration_min_chars: 10,
  prompt_min_dwell_ms: 0,
};

const question: StudyQuestion = {
  id: "q-1",
  kind: "open_response",
  topic: "Graphs",
  prompt: "Explain why a minimum cut separates source from sink.",
  difficulty: "explain",
  content_language: "en",
  translations: [],
  provenance: {
    origin: "lms",
    generated_by: "model",
    generator_ref: "test-model",
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

const ANSWER = "A cut is a partition whose removal disconnects them.";
const EXCERPT =
  "Every s-t cut has capacity at least the value of any flow from s to t.";

const groundedQuestion: StudyQuestion = {
  ...question,
  provenance: {
    ...question.provenance,
    source_spans: [
      {
        content_item_id: "ep-001",
        start_char: null,
        end_char: null,
        start_ms: 0,
        end_ms: 15_000,
        excerpt: EXCERPT,
      },
    ],
  },
};

function renderCard(submitted: string[] = [], card: StudyQuestion = question) {
  const store = new StudySessionStore({
    questions: [card],
    pacing,
    submit: async (submission) => {
      submitted.push(
        `${submission.questionId}:${submission.selfRating}:${submission.confidence}`,
      );
    },
    // No cancel window here: this asserts the button reaches the store, not
    // the undo behaviour study-session-store.test.ts covers.
    retry: { holdMs: 0 },
    now: () => 100_000,
  });
  render(StudyCard, { store });
  return store;
}

/** Press Reveal, then say how sure: every reveal now takes both. */
async function reveal(confidence = /^Somewhat sure/) {
  await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
  await fireEvent.click(screen.getByRole("button", { name: confidence }));
}

describe("study card", () => {
  it("shows the prompt with its provenance", () => {
    renderCard();

    expect(
      screen.getByRole("heading", {
        name: /minimum cut separates source from sink/,
      }),
    ).toBeTruthy();
    expect(screen.getByText("Model-generated")).toBeTruthy();
  });

  it("keeps reveal disabled until the learner has written their own answer", async () => {
    renderCard();
    const reveal = screen.getByRole("button", { name: "Reveal" });

    expect(reveal.hasAttribute("disabled")).toBe(true);

    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: "A cut is a partition whose removal disconnects them." },
    });

    expect(
      screen.getByRole("button", { name: "Reveal" }).hasAttribute("disabled"),
    ).toBe(false);
  });

  it("offers every shortcut as a button too", async () => {
    renderCard();
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: "A cut is a partition whose removal disconnects them." },
    });
    await reveal();

    for (const name of ["Again", "Hard", "Good", "Easy", "Undo", "Pause"]) {
      expect(
        screen.getByRole("button", { name: new RegExp(name) }),
      ).toBeTruthy();
    }
  });

  it("grades from the pointer as well as the keyboard", async () => {
    const submitted: string[] = [];
    renderCard(submitted);
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: "A cut is a partition whose removal disconnects them." },
    });
    await reveal();
    await fireEvent.click(screen.getByRole("button", { name: /Good/ }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(submitted).toEqual(["q-1:3:3"]);
  });

  it("asks with the space key but not while typing an answer", async () => {
    const store = renderCard();
    const answer = screen.getByLabelText("Your answer");
    await fireEvent.input(answer, {
      target: { value: "A cut is a partition whose removal disconnects them." },
    });

    await fireEvent.keyDown(answer, { key: " " });
    expect(store.askingConfidence).toBe(false);

    await fireEvent.keyDown(window, { key: " " });
    expect(store.askingConfidence).toBe(true);
    expect(store.current?.revealed).toBe(false);
  });

  it("asks how sure before the reveal, then shows the excerpts and grades", async () => {
    const submitted: string[] = [];
    renderCard(submitted, groundedQuestion);
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));

    expect(
      screen.getByRole("group", { name: "How sure are you of your answer?" }),
    ).toBeTruthy();
    expect(screen.queryByText(EXCERPT)).toBeNull();
    expect(screen.queryByRole("button", { name: /Good/ })).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: /^Sure/ }));

    expect(screen.getByText(EXCERPT)).toBeTruthy();
    expect(screen.queryByRole("group", { name: /How sure/ })).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: /Good/ }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(submitted).toEqual(["q-1:3:4"]);
  });

  it("takes the confidence from its own keys and leaves 1–4 to the grades", async () => {
    const submitted: string[] = [];
    const store = renderCard(submitted);
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await fireEvent.keyDown(window, { key: " " });

    // A grade key out of habit is not taken as a confidence, nor as a grade.
    await fireEvent.keyDown(window, { key: "1" });
    expect(store.askingConfidence).toBe(true);
    expect(store.current?.revealed).toBe(false);

    await fireEvent.keyDown(window, { key: "t" });
    expect(store.current?.revealed).toBe(true);
    expect(store.current?.confidence).toBe(5);

    await fireEvent.keyDown(window, { key: "2" });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(submitted).toEqual(["q-1:2:5"]);
  });

  it("ignores the confidence keys before Reveal is pressed", async () => {
    const store = renderCard();
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });

    await fireEvent.keyDown(window, { key: "r" });

    expect(store.current?.revealed).toBe(false);
    expect(store.askingConfidence).toBe(false);
  });

  it("flags a card the learner was sure of and graded Again, until they move on", async () => {
    const store = new StudySessionStore({
      questions: [groundedQuestion, { ...question, id: "q-2" }],
      pacing,
      submit: async () => undefined,
      retry: { holdMs: 0 },
      now: () => 100_000,
    });
    render(StudyCard, { store });
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await reveal(/^Certain/);

    await fireEvent.click(screen.getByRole("button", { name: /Again/ }));

    expect(screen.getByText("You were sure of this one.")).toBeTruthy();
    expect(screen.getByText(EXCERPT)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Good/ })).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(store.current?.question.id).toBe("q-2");
    expect(screen.queryByText("You were sure of this one.")).toBeNull();
  });

  it("moves on from a flagged card with the space key", async () => {
    const store = renderCard();
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await reveal(/^Sure/);
    await fireEvent.click(screen.getByRole("button", { name: /Hard/ }));
    expect(store.flagged).toBe(true);

    await fireEvent.keyDown(window, { key: " " });

    expect(store.flagged).toBe(false);
    expect(store.remaining).toBe(0);
  });

  it("does not flag a card the learner was unsure of", async () => {
    renderCard();
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await reveal(/^Unsure/);

    await fireEvent.click(screen.getByRole("button", { name: /Again/ }));

    expect(screen.queryByText("You were sure of this one.")).toBeNull();
  });

  it("lists the confidence keys among the shortcuts", async () => {
    renderCard();

    await fireEvent.keyDown(window, { key: "?" });

    expect(screen.getByText("Q – T")).toBeTruthy();
    expect(
      screen.getByText("Say how sure you are, before the reveal"),
    ).toBeTruthy();
  });

  it("reveals the material the question was generated from", async () => {
    renderCard([], groundedQuestion);
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await reveal();

    expect(
      screen.getByRole("region", {
        name: "What this question was generated from",
      }),
    ).toBeTruthy();
    expect(screen.getByText(EXCERPT)).toBeTruthy();
    // The answer stays in the field; the reveal must not echo it back as if
    // it were something to compare against.
    expect(screen.queryByText(ANSWER)).toBeNull();
  });

  it("names the lecture and the moment each revealed excerpt comes from", async () => {
    renderCard([], {
      ...groundedQuestion,
      provenance: {
        ...groundedQuestion.provenance,
        source_spans: [
          {
            content_item_id: "6a0995b4",
            content_item_title: "Vorlesung - VU vom 2026-10-06",
            start_char: null,
            end_char: null,
            start_ms: 737_670,
            end_ms: 748_200,
            excerpt: EXCERPT,
          },
        ],
      },
    });
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await reveal();

    expect(screen.getByText(EXCERPT)).toBeTruthy();
    expect(
      screen.getByText("Vorlesung - VU vom 2026-10-06, at 12:17"),
    ).toBeTruthy();
  });

  it("says why a card is not from the lectures when they could not be searched", () => {
    renderCard([], { ...question, fallback_reason: "index_unavailable" });

    expect(
      screen.getByText(/^Not from your lectures: they could not be searched/),
    ).toBeTruthy();
  });

  it("says a question with no source material is free recall", async () => {
    renderCard();
    await fireEvent.input(screen.getByLabelText("Your answer"), {
      target: { value: ANSWER },
    });
    await reveal();

    expect(screen.getByText(/^Free recall: /)).toBeTruthy();
    expect(
      screen.queryByRole("region", {
        name: "What this question was generated from",
      }),
    ).toBeNull();
    expect(screen.queryByText(ANSWER)).toBeNull();
  });

  it("announces a pause without losing the card", async () => {
    renderCard();

    await fireEvent.click(screen.getByRole("button", { name: "Pause" }));

    expect(screen.getByText(/Paused/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /minimum cut/ })).toBeTruthy();
  });

  it("keeps the card visible in focus mode", async () => {
    renderCard();

    await fireEvent.click(screen.getByRole("button", { name: "Focus mode" }));

    expect(screen.getByLabelText("Your answer")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /minimum cut/ })).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Focus mode on" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });
});
