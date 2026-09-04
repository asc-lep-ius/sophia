import { describe, expect, it, vi } from "vitest";

import { SophiaApiError } from "../../src/lib/api/client";
import { SubmissionOutbox } from "../../src/lib/study/outbox.svelte";

function apiError(status: number): SophiaApiError {
  return new SophiaApiError({
    detail: { code: "study.failed", params: {} },
    status,
  });
}

describe("submission outbox", () => {
  it("clears an entry once the server accepts it", async () => {
    const outbox = new SubmissionOutbox<string>({
      submit: async () => undefined,
      rollback: vi.fn(),
    });

    await outbox.enqueue("req-1", "grade");

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
      wait: async () => undefined,
    });

    await outbox.enqueue("req-1", "grade");

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
      wait: async () => undefined,
    });

    await outbox.enqueue("req-1", "grade");

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
      wait: async () => undefined,
    });

    await outbox.enqueue("req-1", "grade");

    expect(rollback).toHaveBeenCalledOnce();
    expect(outbox.entries[0]?.attempts).toBe(3);
  });

  it("cannot cancel an entry that has already been sent", async () => {
    const outbox = new SubmissionOutbox<string>({
      submit: async () => undefined,
      rollback: vi.fn(),
    });
    await outbox.enqueue("req-1", "grade");

    expect(outbox.cancel("req-1")).toBe(false);
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
      wait: async () => undefined,
    });
    await outbox.enqueue("req-1", "grade");
    failing = false;

    await outbox.retry("req-1");

    expect(outbox.entries).toEqual([]);
  });
});
