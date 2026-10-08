import { describe, expect, it } from "vitest";

import type { StudyQuestion } from "../../src/lib/api/study";
import { preTestAnswered } from "../../src/lib/study/deck";
import { load } from "../../src/routes/study/[sessionId]/act/+page.server";

const SESSION_ID = 7;

function card(id: string): StudyQuestion {
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
      required_event_types: [
        "prompt_shown",
        "prediction_made",
        "elaboration_written",
      ],
      min_elaboration_chars: 80,
      min_prompt_dwell_ms: 5000,
    },
  };
}

const DECK = [card("anchor"), card("card-1"), card("card-2")];

function openAct(attemptedQuestionIds: string[], questions = DECK) {
  return load({
    parent: async () => ({
      attemptedQuestionIds,
      questions,
      sessionId: SESSION_ID,
    }),
  } as never);
}

describe("act route guard", () => {
  // #107: Resume linked here from a session abandoned on the predict route,
  // and the server refused every grade on it for want of a prediction.
  it("sends a session whose pre-test is not done back to predict", async () => {
    await expect(openAct([])).rejects.toMatchObject({
      status: 303,
      location: `/app/study/${SESSION_ID}/predict`,
    });
  });

  it("does not count a practice card as the pre-test", async () => {
    await expect(openAct(["card-1"])).rejects.toMatchObject({
      location: `/app/study/${SESSION_ID}/predict`,
    });
  });

  it("sends a session with no cards to predict, where they can be generated", async () => {
    await expect(openAct([], [])).rejects.toMatchObject({
      location: `/app/study/${SESSION_ID}/predict`,
    });
  });

  it("opens once the anchor has been answered", async () => {
    await expect(openAct(["anchor"])).resolves.toBeUndefined();
  });
});

describe("preTestAnswered", () => {
  it("is the anchor's attempt and nothing else", () => {
    expect(preTestAnswered(DECK, ["anchor"])).toBe(true);
    expect(preTestAnswered(DECK, ["card-1", "card-2"])).toBe(false);
    expect(preTestAnswered([], ["anchor"])).toBe(false);
  });
});
