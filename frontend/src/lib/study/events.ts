export type StudyStreamStatus = "idle" | "connecting" | "open" | "closed";

export type StudyStreamEvent =
  | {
      type: "attempt_scored";
      attemptId: number;
      questionId: string;
      score: number | null;
    }
  | { type: "prediction_recorded"; topic: string; predicted: number }
  | { type: "self_explanation_recorded"; flashcardId: number }
  | { type: "reflection_recorded"; prompt: string }
  | { type: "flashcard_saved"; flashcardId: number }
  | { type: "gap"; reason: string };

export type StudyStreamHandlers = {
  onEvent?: (event: StudyStreamEvent) => void;
  onStatus?: (status: StudyStreamStatus) => void;
};

export type StudyStreamOptions = StudyStreamHandlers & {
  sessionId: number;
  basePath?: string;
  createSource?: (url: string) => EventSource;
};

const STREAM_EVENT_TYPES = [
  "attempt_scored",
  "prediction_recorded",
  "self_explanation_recorded",
  "reflection_recorded",
  "flashcard_saved",
  "gap",
] as const;

/**
 * Typed wrapper over the study event stream.
 *
 * Native `EventSource` cannot set headers, so the stream authenticates with
 * the same-origin session cookie and reconnects (with `Last-Event-ID`) on its
 * own — this adds the typing and the gap handling, not a reconnect loop of its
 * own. Anything arriving here is a *notification*: the durable state is what
 * the submission endpoints returned, so a dropped event costs a refresh at
 * worst, never a lost grade.
 */
export class StudyEventStream {
  #source: EventSource | null = null;
  #options: StudyStreamOptions;

  constructor(options: StudyStreamOptions) {
    this.#options = options;
  }

  get url(): string {
    const base = this.#options.basePath ?? "/api";
    return `${base}/study/${this.#options.sessionId}/events`;
  }

  connect(): void {
    if (this.#source) {
      return;
    }
    const create =
      this.#options.createSource ??
      ((url: string) => new EventSource(url, { withCredentials: true }));

    this.#options.onStatus?.("connecting");
    const source = create(this.url);
    this.#source = source;

    source.onopen = () => this.#options.onStatus?.("open");
    source.onerror = () => {
      // EventSource retries by itself; report the gap rather than tearing the
      // stream down, so a flaky connection does not end the session's updates.
      this.#options.onStatus?.(
        source.readyState === EventSource.CLOSED ? "closed" : "connecting",
      );
    };

    for (const eventType of STREAM_EVENT_TYPES) {
      source.addEventListener(eventType, (event) => {
        const parsed = parseStreamEvent(
          eventType,
          event as MessageEvent<string>,
        );
        if (parsed) {
          this.#options.onEvent?.(parsed);
        }
      });
    }
  }

  close(): void {
    this.#source?.close();
    this.#source = null;
    this.#options.onStatus?.("closed");
  }
}

export function parseStreamEvent(
  eventType: (typeof STREAM_EVENT_TYPES)[number],
  event: MessageEvent<string>,
): StudyStreamEvent | null {
  const payload = parseJsonObject(event.data);
  if (!payload) {
    return null;
  }

  switch (eventType) {
    case "attempt_scored":
      return {
        type: "attempt_scored",
        attemptId: numberOr(payload.attempt_id, 0),
        questionId: stringOr(payload.question_id, ""),
        score: typeof payload.score === "number" ? payload.score : null,
      };
    case "prediction_recorded":
      return {
        type: "prediction_recorded",
        topic: stringOr(payload.topic, ""),
        predicted: numberOr(payload.predicted, 0),
      };
    case "self_explanation_recorded":
      return {
        type: "self_explanation_recorded",
        flashcardId: numberOr(payload.flashcard_id, 0),
      };
    case "reflection_recorded":
      return {
        type: "reflection_recorded",
        prompt: stringOr(payload.prompt, ""),
      };
    case "flashcard_saved":
      return {
        type: "flashcard_saved",
        flashcardId: numberOr(payload.flashcard_id, 0),
      };
    case "gap":
      return { type: "gap", reason: stringOr(payload.reason, "unknown") };
  }
}

function parseJsonObject(raw: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function stringOr(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}
