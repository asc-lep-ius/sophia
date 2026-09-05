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

function renderCard(submitted: string[] = []) {
  const store = new StudySessionStore({
    questions: [question],
    pacing,
    submit: async (submission) => {
      submitted.push(`${submission.questionId}:${submission.selfRating}`);
    },
    // No cancel window here: this asserts the button reaches the store, not
    // the undo behaviour study-session-store.test.ts covers.
    retry: { holdMs: 0 },
    now: () => 100_000,
  });
  render(StudyCard, { store });
  return store;
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
    await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));

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
    await fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    await fireEvent.click(screen.getByRole("button", { name: /Good/ }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(submitted).toEqual(["q-1:3"]);
  });

  it("reveals with the space key but not while typing an answer", async () => {
    const store = renderCard();
    const answer = screen.getByLabelText("Your answer");
    await fireEvent.input(answer, {
      target: { value: "A cut is a partition whose removal disconnects them." },
    });

    await fireEvent.keyDown(answer, { key: " " });
    expect(store.current?.revealed).toBe(false);

    await fireEvent.keyDown(window, { key: " " });
    expect(store.current?.revealed).toBe(true);
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
