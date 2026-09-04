import { describe, expect, it, vi } from "vitest";

import type { LearningEventInput } from "../../src/lib/api/study";
import { LearningEventBatcher } from "../../src/lib/study/learningEvents";

type Batch = LearningEventInput[];

function batcher(send: (context: unknown, events: Batch) => Promise<void>) {
  const scheduled: (() => void)[] = [];
  let nextId = 0;
  const instance = new LearningEventBatcher({
    csrfToken: "csrf",
    learningPathId: 12,
    sessionId: 7,
    send,
    now: () => new Date("2026-09-04T10:00:00.000Z"),
    newId: () => `event-${(nextId += 1)}`,
    schedule: (callback) => {
      scheduled.push(callback);
      return scheduled.length;
    },
    cancel: () => undefined,
  });
  return { instance, runTimer: () => scheduled.pop()?.() };
}

describe("learning event batcher", () => {
  it("buffers events until something flushes them", () => {
    const send = vi.fn(async () => undefined);
    const { instance } = batcher(send);

    instance.record({ eventType: "prompt_shown", payload: { dwell_ms: 900 } });

    expect(send).not.toHaveBeenCalled();
    expect(instance.pendingCount).toBe(1);
  });

  it("stamps every event with the session and an idempotency key", async () => {
    const batches: Batch[] = [];
    const { instance } = batcher(async (_context, events) => {
      batches.push(events);
    });

    instance.record({
      eventType: "elaboration_written",
      questionId: "q-1",
      payload: { text_length: 120 },
    });
    await instance.flushNow();

    expect(batches).toEqual([
      [
        {
          event_id: "event-1",
          event_type: "elaboration_written",
          occurred_at: "2026-09-04T10:00:00.000Z",
          session_id: 7,
          question_id: "q-1",
          payload: { text_length: 120 },
        },
      ],
    ]);
  });

  it("keeps the batch buffered when ingestion fails", async () => {
    const { instance } = batcher(async () => {
      throw new Error("offline");
    });
    instance.record({ eventType: "prediction_made" });

    await expect(instance.flushNow()).rejects.toThrow("offline");
    expect(instance.pendingCount).toBe(1);
  });

  it("flushes on its own timer as well", async () => {
    const send = vi.fn(async () => undefined);
    const { instance, runTimer } = batcher(send);

    instance.record({ eventType: "prompt_shown" });
    runTimer();
    await vi.waitFor(() => expect(send).toHaveBeenCalledOnce());
  });

  it("splits a batch larger than the ingestion limit", async () => {
    const sizes: number[] = [];
    const { instance } = batcher(async (_context, events) => {
      sizes.push(events.length);
    });

    for (let index = 0; index < 150; index += 1) {
      instance.record({ eventType: "prompt_shown" });
    }
    await instance.flushNow();

    expect(sizes).toEqual([100, 50]);
  });
});
