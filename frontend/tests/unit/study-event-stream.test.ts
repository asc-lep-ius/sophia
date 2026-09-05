import { describe, expect, it, vi } from "vitest";

import {
  StudyEventStream,
  parseStreamEvent,
  type StudyStreamEvent,
  type StudyStreamStatus,
} from "../../src/lib/study/events";

type Listener = (event: MessageEvent<string>) => void;

class FakeEventSource {
  static readonly CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  readonly listeners = new Map<string, Listener>();

  constructor(readonly url: string) {}

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, listener);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: string): void {
    this.listeners.get(type)?.(new MessageEvent(type, { data }));
  }
}

function message(data: string): MessageEvent<string> {
  return new MessageEvent("message", { data });
}

describe("study event stream", () => {
  it("streams from the session's same-origin API path", () => {
    const stream = new StudyEventStream({ sessionId: 42 });

    expect(stream.url).toBe("/api/study/42/events");
  });

  it("reports connection status and typed events", () => {
    const statuses: StudyStreamStatus[] = [];
    const events: StudyStreamEvent[] = [];
    let source: FakeEventSource | null = null;

    const stream = new StudyEventStream({
      sessionId: 7,
      onStatus: (status) => statuses.push(status),
      onEvent: (event) => events.push(event),
      createSource: (url) => {
        source = new FakeEventSource(url);
        return source as unknown as EventSource;
      },
    });
    stream.connect();
    source!.onopen?.();
    source!.emit(
      "attempt_scored",
      JSON.stringify({ attempt_id: 3, question_id: "q-1", score: 0.7 }),
    );

    expect(statuses).toEqual(["connecting", "open"]);
    expect(events).toEqual([
      { type: "attempt_scored", attemptId: 3, questionId: "q-1", score: 0.7 },
    ]);
  });

  it("closes the underlying source once", () => {
    let source: FakeEventSource | null = null;
    const stream = new StudyEventStream({
      sessionId: 7,
      createSource: (url) => {
        source = new FakeEventSource(url);
        return source as unknown as EventSource;
      },
    });
    stream.connect();
    stream.close();

    expect(source!.closed).toBe(true);
  });

  it("does not open a second source for the same stream", () => {
    const createSource = vi.fn(
      (url: string) => new FakeEventSource(url) as unknown as EventSource,
    );
    const stream = new StudyEventStream({ sessionId: 7, createSource });

    stream.connect();
    stream.connect();

    expect(createSource).toHaveBeenCalledOnce();
  });

  it("surfaces a retention gap so the client can resynchronise", () => {
    expect(
      parseStreamEvent("gap", message(JSON.stringify({ reason: "retention" }))),
    ).toEqual({ type: "gap", reason: "retention" });
  });

  it("drops a malformed frame instead of throwing at the learner", () => {
    expect(parseStreamEvent("attempt_scored", message("not json"))).toBeNull();
  });

  it("tolerates a frame missing the fields it expects", () => {
    expect(parseStreamEvent("attempt_scored", message("{}"))).toEqual({
      type: "attempt_scored",
      attemptId: 0,
      questionId: "",
      score: null,
    });
  });
});
