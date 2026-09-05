import { ingestLearningEvents, type LearningEventInput } from "$lib/api/study";

export type LearningEventType = LearningEventInput["event_type"];

export type LearningEventDraft = {
  eventType: LearningEventType;
  questionId?: string | null;
  payload?: Record<string, boolean | number | string | null>;
};

export type LearningEventBatcherOptions = {
  csrfToken: string;
  learningPathId: number;
  sessionId: number;
  flushIntervalMs?: number;
  send?: typeof ingestLearningEvents;
  now?: () => Date;
  newId?: () => string;
  schedule?: (callback: () => void, delayMs: number) => number;
  cancel?: (handle: number) => void;
};

export const DEFAULT_FLUSH_INTERVAL_MS = 5000;
const MAX_BATCH_SIZE = 100;

/**
 * Buffers the learner's process trace and posts it in batches.
 *
 * The trace is not telemetry: the server refuses an answer whose required
 * events it has not ingested, so `flushNow` has to be awaited before an
 * attempt is submitted. Timer-driven batching alone would race the very
 * submission it is meant to authorise.
 *
 * Instantiated per route, never at module scope — module-level state would be
 * shared across SSR requests.
 */
export class LearningEventBatcher {
  #pending: LearningEventInput[] = [];
  #timer: number | null = null;
  #flushing: Promise<void> | null = null;
  #keepalive = false;
  #options: Required<Omit<LearningEventBatcherOptions, "flushIntervalMs">> & {
    flushIntervalMs: number;
  };

  constructor(options: LearningEventBatcherOptions) {
    this.#options = {
      flushIntervalMs: options.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS,
      csrfToken: options.csrfToken,
      learningPathId: options.learningPathId,
      sessionId: options.sessionId,
      send: options.send ?? ingestLearningEvents,
      now: options.now ?? (() => new Date()),
      newId: options.newId ?? (() => crypto.randomUUID()),
      schedule:
        options.schedule ??
        ((callback, delayMs) =>
          setTimeout(callback, delayMs) as unknown as number),
      cancel: options.cancel ?? ((handle) => clearTimeout(handle)),
    };
  }

  get pendingCount(): number {
    return this.#pending.length;
  }

  record(draft: LearningEventDraft): void {
    this.#pending.push({
      event_id: this.#options.newId(),
      event_type: draft.eventType,
      occurred_at: this.#options.now().toISOString(),
      session_id: this.#options.sessionId,
      question_id: draft.questionId ?? null,
      payload: draft.payload ?? {},
    });
    this.#scheduleFlush();
  }

  /**
   * Post everything buffered.
   *
   * Concurrent calls share one flush: teardown triggers this from two
   * directions at once (its own call, and the held grade whose submission
   * awaits it), and two flushes reading the same buffer would post the same
   * batch twice.
   */
  flushNow(): Promise<void> {
    this.#flushing ??= this.#drain().finally(() => {
      this.#flushing = null;
    });
    return this.#flushing;
  }

  /** Post what is buffered in a way that can outlive the page. */
  flushOnUnload(): void {
    this.#keepalive = true;
    this.flushQuietly();
  }

  /** The page was restored from the bfcache; stop using the unload path. */
  resumeFromUnload(): void {
    this.#keepalive = false;
  }

  async #drain(): Promise<void> {
    this.#cancelFlush();
    while (this.#pending.length > 0) {
      const batch = this.#pending.slice(0, MAX_BATCH_SIZE);
      // A failure propagates with the batch still buffered: these events are
      // the learner's evidence that they did the work, and dropping them
      // would fail their next submission.
      await this.#options.send(
        {
          csrfToken: this.#options.csrfToken,
          learningPathId: this.#options.learningPathId,
        },
        batch,
        { keepalive: this.#keepalive },
      );
      this.#pending = this.#pending.slice(batch.length);
    }
  }

  /** Best-effort flush for teardown paths that cannot await or recover. */
  flushQuietly(): void {
    void this.flushNow().catch(() => undefined);
  }

  destroy(): void {
    this.#cancelFlush();
  }

  #scheduleFlush(): void {
    if (this.#timer !== null) {
      return;
    }
    this.#timer = this.#options.schedule(() => {
      this.#timer = null;
      this.flushQuietly();
    }, this.#options.flushIntervalMs);
  }

  #cancelFlush(): void {
    if (this.#timer === null) {
      return;
    }
    this.#options.cancel(this.#timer);
    this.#timer = null;
  }
}
