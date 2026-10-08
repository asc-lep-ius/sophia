import { describe, expect, it } from "vitest";

import type { StudyPacing, StudyQuestion } from "../../src/lib/api/study";
import { sessionDrafts, type DraftStore } from "../../src/lib/study/drafts";
import { StudySessionStore } from "../../src/lib/study/session.svelte";

const pacing: StudyPacing = {
  reflection_min_seconds: 30,
  elaboration_min_chars: 10,
  prompt_min_dwell_ms: 0,
};

const ANSWER = "An answer long enough to satisfy the elaboration floor.";

function question(id: string): StudyQuestion {
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
      min_elaboration_chars: 10,
      min_prompt_dwell_ms: 0,
    },
  };
}

/** A Storage double: jsdom's is shared by every test in the file. */
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => {
      items.delete(key);
    },
    setItem: (key, value) => {
      items.set(key, value);
    },
  };
}

function storeWith(
  drafts: DraftStore,
  submit: () => Promise<void> = async () => undefined,
): StudySessionStore {
  return new StudySessionStore({
    questions: [question("q-0"), question("q-1")],
    pacing,
    drafts,
    submit,
    retry: { maxAttempts: 1, holdMs: 0, wait: async () => undefined },
  });
}

async function settle(): Promise<void> {
  for (let turn = 0; turn < 4; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

describe("sessionDrafts", () => {
  it("keeps a draft per session and scope", () => {
    const storage = memoryStorage();
    sessionDrafts(7, "practice", storage).write("q-0", ANSWER);

    expect(sessionDrafts(7, "practice", storage).read("q-0")).toBe(ANSWER);
    expect(sessionDrafts(8, "practice", storage).read("q-0")).toBeNull();
    // The anchor is answered twice: the pre-test's text must not come back
    // as the post-test's.
    expect(sessionDrafts(7, "post_test", storage).read("q-0")).toBeNull();
  });

  it("forgets a draft that is emptied rather than storing an empty string", () => {
    const storage = memoryStorage();
    const drafts = sessionDrafts(7, "practice", storage);
    drafts.write("q-0", ANSWER);

    drafts.write("q-0", "");

    expect(storage.length).toBe(0);
  });

  it("is inert where there is no storage, as during SSR", () => {
    const drafts = sessionDrafts(7, "practice", null);
    drafts.write("q-0", ANSWER);

    expect(drafts.read("q-0")).toBeNull();
  });

  it("does not let a full store break the answer being written", () => {
    const storage = memoryStorage();
    storage.setItem = () => {
      throw new DOMException("full", "QuotaExceededError");
    };

    expect(() =>
      sessionDrafts(7, "practice", storage).write("q-0", ANSWER),
    ).not.toThrow();
  });
});

describe("study session store drafts", () => {
  // #108: every card was seeded with an empty answer, so a step change —
  // which rebuilds the store — threw away whatever the learner had written.
  it("gives a rebuilt store back the answer the last one was writing", () => {
    const drafts = sessionDrafts(7, "practice", memoryStorage());
    storeWith(drafts).setAnswer(ANSWER);

    const rebuilt = storeWith(drafts);

    expect(rebuilt.answer).toBe(ANSWER);
    expect(rebuilt.canReveal).toBe(true);
  });

  it("drops the draft once the server has accepted the grade", async () => {
    const drafts = sessionDrafts(7, "practice", memoryStorage());
    const store = storeWith(drafts);
    store.setAnswer(ANSWER);
    store.reveal();

    store.grade(3);
    await settle();

    expect(drafts.read("q-0")).toBeNull();
  });

  it("keeps the draft when the grade is refused", async () => {
    const drafts = sessionDrafts(7, "practice", memoryStorage());
    const store = storeWith(drafts, async () => {
      throw new TypeError("network down");
    });
    store.setAnswer(ANSWER);
    store.reveal();

    store.grade(3);
    await settle();

    expect(store.state).toBe("rollback");
    expect(drafts.read("q-0")).toBe(ANSWER);
  });
});
