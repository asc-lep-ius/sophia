import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

import { render, screen } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import { completeReview } from "../../src/lib/api/review";
import ReviewCard from "../../src/lib/components/review/ReviewCard.svelte";
import {
  REVIEW_MAX_SENDS,
  ReviewQueueStore,
} from "../../src/lib/review/queue.svelte";
import { load as reviewLoad } from "../../src/routes/review/+page.server";
import GradeBar from "../../src/lib/components/study/GradeBar.svelte";

const PACING = { minPromptDwellMs: 0, minRecallChars: 5 };

type ReviewLoadData = {
  csrfToken: string | null;
  learningPathId: number | null;
  pacing: {
    elaboration_min_chars: number;
    prompt_min_dwell_ms: number;
    reflection_min_seconds: number;
  };
};

type ApiCall = [string, RequestInit | undefined];

function queue(
  topics: string[],
  submit = vi.fn(async () => {}),
): ReviewQueueStore {
  let id = 0;
  return new ReviewQueueStore({
    newId: () => `request-${(id += 1)}`,
    pacing: PACING,
    retry: { holdMs: 0, wait: async () => {} },
    submit,
    topics,
  });
}

describe("review queue", () => {
  it("holds the reveal until a recall attempt has actually been written", () => {
    const store = queue(["Graphs"]);

    expect(store.canReveal).toBe(false);
    store.setRecall("abc");
    expect(store.canReveal).toBe(false);
    store.setRecall("a real attempt");
    expect(store.canReveal).toBe(true);
  });

  it("refuses to grade a topic the learner has not checked themselves on", () => {
    const store = queue(["Graphs"]);
    store.setRecall("a real attempt");

    expect(store.grade(3)).toBe(false);
    store.reveal();
    expect(store.grade(3)).toBe(true);
  });

  it("sends the rating the learner pressed and nothing it was converted into", async () => {
    const submit = vi.fn(async () => {});
    const store = queue(["Graphs", "Sorting"], submit);
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(2);
    await vi.waitFor(() => expect(submit).toHaveBeenCalled());

    const submissions = submit.mock.calls as unknown as [
      { selfRating: number; topic: string },
    ][];
    expect(submissions[0]?.[0]).toMatchObject({
      selfRating: 2,
      topic: "Graphs",
    });
  });

  it("puts a rejected topic back rather than counting it as reviewed", async () => {
    const submit = vi.fn(async () => {
      throw new Error("refused");
    });
    const store = queue(["Graphs", "Sorting"], submit);
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(4);

    await vi.waitFor(() => expect(store.failedCount).toBe(1));
    expect(store.current?.topic).toBe("Graphs");
    expect(store.gradedCount).toBe(0);
    expect(store.error).toBe("review.grade_rejected");
  });

  it("sends each review exactly once, because the API has no request id", async () => {
    const submit = vi.fn(async () => {
      throw new Error("refused");
    });
    const store = queue(["Graphs"], submit);
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(3);

    await vi.waitFor(() => expect(store.failedCount).toBe(1));
    // A retried completion the server already took would advance the FSRS
    // schedule a second time; the learner gets a button instead.
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("moves the queue on when a retry finally succeeds", async () => {
    let refuse = true;
    const submit = vi.fn(async () => {
      if (refuse) {
        throw new Error("refused");
      }
    });
    const store = queue(["Graphs", "Sorting"], submit);
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(3);
    await vi.waitFor(() => expect(store.failedCount).toBe(1));
    expect(store.current?.topic).toBe("Graphs");

    refuse = false;
    const rejected = store.outboxEntries.find(
      (entry) => entry.status === "failed",
    );
    await store.retryFailed(rejected?.requestId ?? "");

    // The server now holds Graphs. Leaving it in front of the learner,
    // revealed and with the grade bar showing, makes grading it twice the
    // obvious next action — and the endpoint has no request id to fold the
    // second one back into the first.
    expect(store.current?.topic).toBe("Sorting");
    expect(store.gradedCount).toBe(1);
  });

  it("does not rewind onto a topic the server already took", async () => {
    const inFlight: { resolve: () => void; reject: (error: Error) => void }[] =
      [];
    const submit = vi.fn(
      () =>
        new Promise<void>((resolve, reject) => {
          inFlight.push({ reject, resolve });
        }),
    );
    const store = queue(["Graphs", "Sorting", "Hashing"], submit);

    store.setRecall("a real attempt");
    store.reveal();
    store.grade(3);
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(3);

    inFlight[1]?.resolve();
    await vi.waitFor(() => expect(store.gradedCount).toBe(2));
    inFlight[0]?.reject(new Error("refused"));
    await vi.waitFor(() => expect(store.failedCount).toBe(1));

    expect(store.current?.topic).toBe("Graphs");

    // Rewinding to the rejected card stepped back over Sorting, which the
    // server accepted while Graphs was in flight. Regrading Graphs must not
    // land the learner on it again.
    store.grade(4);
    expect(store.current?.topic).toBe("Hashing");
  });

  it("stops offering a retry once the send ceiling is reached", async () => {
    const submit = vi.fn(async () => {
      throw new Error("refused");
    });
    const store = queue(["Graphs"], submit);
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(3);
    await vi.waitFor(() => expect(store.failedCount).toBe(1));

    const requestId =
      store.outboxEntries.find((entry) => entry.status === "failed")
        ?.requestId ?? "";
    expect(store.canRetry(requestId)).toBe(true);
    await store.retryFailed(requestId);
    await store.retryFailed(requestId);

    // Three sends in total. Each one is a write the endpoint cannot dedupe,
    // so the button goes quiet rather than staying live and doing nothing.
    expect(submit).toHaveBeenCalledTimes(REVIEW_MAX_SENDS);
    expect(store.canRetry(requestId)).toBe(false);
    await store.retryFailed(requestId);
    expect(submit).toHaveBeenCalledTimes(REVIEW_MAX_SENDS);
  });

  it("takes a review back while it is still held", () => {
    const store = new ReviewQueueStore({
      newId: () => "request-1",
      pacing: PACING,
      retry: { holdMs: 5000 },
      submit: vi.fn(async () => {}),
      topics: ["Graphs", "Sorting"],
    });
    store.setRecall("a real attempt");
    store.reveal();
    store.grade(1);

    expect(store.current?.topic).toBe("Sorting");
    expect(store.undo()).toBe(true);
    expect(store.current?.topic).toBe("Graphs");
    expect(store.gradedCount).toBe(0);
  });
});

describe("review card reuse", () => {
  it("grades through the same bar the study surface uses", () => {
    const store = queue(["Graphs"]);
    store.setRecall("a real attempt");
    store.reveal();

    const review = render(ReviewCard, { store });
    const study = render(GradeBar, { onGrade: () => {} });

    // The same component, so the scale, the labels, the shortcut hints and the
    // thumb-zone target sizes cannot drift apart between the two surfaces.
    expect(gradeLabels(review.container)).toHaveLength(4);
    expect(gradeLabels(study.container)).toEqual(gradeLabels(review.container));
  });

  it("writes the recall into the shared answer field", () => {
    const store = queue(["Graphs"]);
    render(ReviewCard, { store });

    expect(screen.getByLabelText("Your answer")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check myself" })).toBeTruthy();
  });
});

describe("review grading stays on the server", () => {
  it("posts the pressed rating, never a score", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ schedule: { topic: "Graphs" } }), {
          headers: { "content-type": "application/json" },
          status: 200,
        }),
    );
    vi.stubGlobal("fetch", fetch);
    // The client posts a same-origin relative path, which a browser resolves
    // and Node's Request does not. Resolving it here keeps the assertion about
    // the body rather than about the test environment.
    vi.stubGlobal(
      "Request",
      class extends Request {
        constructor(input: RequestInfo | URL, init?: RequestInit) {
          super(
            typeof input === "string"
              ? new URL(input, "http://localhost")
              : input,
            init,
          );
        }
      },
    );

    await completeReview(
      { csrfToken: "csrf", learningPathId: 12 },
      { selfRating: 3, topic: "Graphs" },
    );

    const sent = fetch.mock.calls as unknown as [Request][];
    const request = sent[0]?.[0];
    const body = JSON.parse(await (request as Request).text());
    expect(body).toEqual({
      learning_path_id: 12,
      self_rating: 3,
      topic: "Graphs",
    });
    expect(body).not.toHaveProperty("score");
    vi.unstubAllGlobals();
  });

  it("keeps scheduling and grading maths out of the review sources", async () => {
    const sources = await reviewSources();

    for (const [path, content] of sources) {
      // The FSRS parameters and the Again/Hard/Good/Easy scale live in
      // `sophia.services.athena_review`. A copy here would be a second input
      // to the schedule that nobody could change without finding both.
      expect(content, path).not.toMatch(
        /\b(stability|difficulty|interval_days)\s*[*+/-]/,
      );
      // Loose enough to catch the shape the constant is really written in,
      // `{1: 0.0, 2: 0.3, 3: 0.7, 4: 1.0}`, not just an array literal — the
      // earlier pattern required `0.3` and `0.7` to be adjacent and so would
      // have missed the most likely copy.
      expect(content, path).not.toMatch(/0\.3\s*[,:][^\n]{0,16}0\.7/);
      // Names that imply a score *mapping*. `self_rating` itself is not in
      // the list: sending the pressed button over the wire is the whole point,
      // and matching it would fail on the one call that is correct.
      expect(content, path).not.toMatch(
        /\bcompute_?fsrs|rating_?scores|selfratingscore|ratingtoscore/i,
      );
    }
    expect(sources.length).toBeGreaterThan(0);
  });
});

describe("review server load", () => {
  it("scopes the due list to the session tenant and reuses the study pacing floors", async () => {
    const fetch = vi.fn(async (url: string) =>
      url.startsWith("/api/study/pacing")
        ? jsonResponse({
            elaboration_min_chars: 40,
            prompt_min_dwell_ms: 2000,
            reflection_min_seconds: 20,
          })
        : jsonResponse({ learning_path_id: 12, reviews: [] }),
    );
    const event = createEvent({
      fetch,
      url: "http://localhost/app/review?learning_path_id=99",
    });

    const data = (await reviewLoad(event as never)) as ReviewLoadData;

    const dueCall = apiCalls(fetch).find((call) =>
      call[0].startsWith("/api/review/due"),
    );
    expect(dueCall?.[0]).toContain("learning_path_id=12");
    expect(dueCall?.[0]).not.toContain("learning_path_id=99");
    expect(data.pacing.elaboration_min_chars).toBe(40);
  });

  it("keeps the stricter floors when the pacing endpoint is unreachable", async () => {
    const event = createEvent({
      fetch: vi.fn(async (url: string) =>
        url.startsWith("/api/study/pacing")
          ? new Response(null, { status: 503 })
          : jsonResponse({ learning_path_id: 12, reviews: [] }),
      ),
    });

    const data = (await reviewLoad(event as never)) as ReviewLoadData;

    // A review that let the learner reveal instantly because a service was
    // down would quietly turn retrieval practice into re-reading.
    expect(data.pacing.elaboration_min_chars).toBeGreaterThan(0);
    expect(data.pacing.prompt_min_dwell_ms).toBeGreaterThan(0);
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    const event = createEvent({ authenticated: false, fetch: vi.fn() });

    await expect(reviewLoad(event as never)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });
});

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

function createEvent({
  authenticated = true,
  fetch,
  url = "http://localhost/app/review",
}: {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  url?: string;
}): RequestEvent {
  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated,
      csrfToken: "csrf-from-session",
      learning_path_id: "12",
      locale: "en",
      org_id: "tu-wien",
      request_id: "req-review",
      role: "student",
      sessionSettings: null,
      tenant: { learning_path_id: "12", org_id: "tu-wien", role: "student" },
      user: null,
    },
    request: new Request(url),
    url: new URL(url),
  } as unknown as RequestEvent;
}

function apiCalls(fetch: ReturnType<typeof vi.fn>): ApiCall[] {
  return fetch.mock.calls as unknown as ApiCall[];
}

function gradeLabels(container: HTMLElement): (string | undefined)[] {
  return [...container.querySelectorAll("[data-grade]")].map((button) =>
    button.textContent?.trim(),
  );
}

async function reviewSources(): Promise<[string, string][]> {
  const roots = [
    "src/lib/review",
    "src/lib/components/review",
    "src/routes/review",
    "src/lib/api/review.ts",
  ];
  const files: [string, string][] = [];
  for (const root of roots) {
    await collect(root, files);
  }
  return files;
}

async function collect(path: string, files: [string, string][]): Promise<void> {
  if (path.endsWith(".ts") || path.endsWith(".svelte")) {
    files.push([path, await readFile(path, "utf8")]);
    return;
  }
  for (const entry of await readdir(path, { withFileTypes: true })) {
    await collect(join(path, entry.name), files);
  }
}
