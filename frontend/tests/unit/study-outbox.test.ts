import { describe, expect, it, vi } from "vitest";

import { SophiaApiError } from "../../src/lib/api/client";
import { SubmissionOutbox } from "../../src/lib/study/outbox.svelte";

function apiError(status: number): SophiaApiError {
  return new SophiaApiError({
    detail: { code: "study.failed", params: {} },
    status,
  });
}

/** Let the outbox's own promise chain finish before asserting. */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 4; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

describe("submission outbox", () => {
  it("clears an entry once the server accepts it", async () => {
    const outbox = new SubmissionOutbox<string>({
      submit: async () => undefined,
      rollback: vi.fn(),
      holdMs: 0,
    });

    outbox.enqueue("req-1", "grade");
    await settle();

    expect(outbox.entries).toEqual([]);
    expect(outbox.pendingCount).toBe(0);
  });

  it("retries a server failure with the same request id", async () => {
    const seen: string[] = [];
    let calls = 0;
    const outbox = new SubmissionOutbox<string>({
      submit: async (_payload, requestId) => {
        seen.push(requestId);
        calls += 1;
        if (calls === 1) {
          throw apiError(503);
        }
      },
      rollback: vi.fn(),
      holdMs: 0,
      wait: async () => undefined,
    });

    outbox.enqueue("req-1", "grade");
    await settle();

    expect(seen).toEqual(["req-1", "req-1"]);
    expect(outbox.entries).toEqual([]);
  });

  it("rolls back rather than retrying a refusal the server will repeat", async () => {
    const rollback = vi.fn();
    const submit = vi.fn(async () => {
      throw apiError(412);
    });
    const outbox = new SubmissionOutbox<string>({
      submit,
      rollback,
      holdMs: 0,
      wait: async () => undefined,
    });

    outbox.enqueue("req-1", "grade");
    await settle();

    expect(submit).toHaveBeenCalledTimes(1);
    expect(rollback).toHaveBeenCalledOnce();
    expect(outbox.failedCount).toBe(1);
  });

  it("rolls back after the retry budget runs out", async () => {
    const rollback = vi.fn();
    const outbox = new SubmissionOutbox<string>({
      submit: async () => {
        throw apiError(500);
      },
      rollback,
      maxAttempts: 3,
      holdMs: 0,
      wait: async () => undefined,
    });

    outbox.enqueue("req-1", "grade");
    await settle();

    expect(rollback).toHaveBeenCalledOnce();
    expect(outbox.entries[0]?.attempts).toBe(3);
  });

  it("cancels an entry still inside its hold window, and never sends it", async () => {
    const submit = vi.fn(async () => undefined);
    const outbox = new SubmissionOutbox<string>({
      submit,
      rollback: vi.fn(),
      holdMs: 10_000,
    });
    outbox.enqueue("req-1", "grade");

    expect(outbox.cancel("req-1")).toBe(true);
    await settle();
    expect(submit).not.toHaveBeenCalled();
    expect(outbox.entries).toEqual([]);
  });

  it("cannot cancel an entry that has already been sent", async () => {
    const outbox = new SubmissionOutbox<string>({
      submit: async () => undefined,
      rollback: vi.fn(),
      holdMs: 0,
    });
    outbox.enqueue("req-1", "grade");
    await settle();

    expect(outbox.cancel("req-1")).toBe(false);
  });

  it("reports whether an entry can still be taken back", async () => {
    const outbox = new SubmissionOutbox<string>({
      submit: async () => undefined,
      rollback: vi.fn(),
      holdMs: 10_000,
    });
    outbox.enqueue("req-1", "grade");

    expect(outbox.canCancel("req-1")).toBe(true);
    outbox.flush();
    expect(outbox.canCancel("req-1")).toBe(false);
    await settle();
  });

  it("forgets a failed entry a fresh submission supersedes", async () => {
    const outbox = new SubmissionOutbox<string>({
      submit: async () => {
        throw apiError(412);
      },
      rollback: vi.fn(),
      holdMs: 0,
      wait: async () => undefined,
    });
    outbox.enqueue("req-1", "grade");
    await settle();
    expect(outbox.failedCount).toBe(1);

    outbox.discardFailed((entry) => entry.payload === "grade");

    expect(outbox.failedCount).toBe(0);
    expect(outbox.entries).toEqual([]);
  });

  it("flushes held entries when the surface goes away", async () => {
    const submit = vi.fn(async () => undefined);
    const outbox = new SubmissionOutbox<string>({
      submit,
      rollback: vi.fn(),
      holdMs: 10_000,
    });
    outbox.enqueue("req-1", "grade");

    outbox.flush();
    await settle();

    expect(submit).toHaveBeenCalledOnce();
  });

  it("retries a failed entry on demand", async () => {
    let failing = true;
    const outbox = new SubmissionOutbox<string>({
      submit: async () => {
        if (failing) {
          throw apiError(412);
        }
      },
      rollback: vi.fn(),
      holdMs: 0,
      wait: async () => undefined,
    });
    outbox.enqueue("req-1", "grade");
    await settle();
    failing = false;

    await outbox.retry("req-1");

    expect(outbox.entries).toEqual([]);
  });
});
