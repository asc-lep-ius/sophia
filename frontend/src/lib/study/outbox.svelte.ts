import { SvelteMap } from "svelte/reactivity";

import { SophiaApiError } from "$lib/api/client";
import { isRetryableFailure } from "$lib/api/study";

export type OutboxEntryStatus = "pending" | "retrying" | "failed";

export type OutboxEntry<T> = {
  requestId: string;
  payload: T;
  status: OutboxEntryStatus;
  attempts: number;
};

export type OutboxOptions<T> = {
  submit: (payload: T, requestId: string) => Promise<void>;
  rollback: (entry: OutboxEntry<T>, error: unknown) => void;
  maxAttempts?: number;
  retryDelayMs?: number;
  /** How long an entry can still be cancelled before it is sent. */
  holdMs?: number;
  wait?: (delayMs: number) => Promise<void>;
};

export const DEFAULT_MAX_ATTEMPTS = 3;
export const DEFAULT_RETRY_DELAY_MS = 400;

/**
 * The window in which undo can still take a grade back.
 *
 * Dispatching the instant a grade is entered leaves nothing to cancel — the
 * request is already in flight, so "undo" could only ever apologise. Holding
 * the submission for a moment is what makes the documented behaviour real, and
 * it costs nothing: the surface has already moved on optimistically, and
 * `flush` sends everything the moment the page is leaving.
 */
export const DEFAULT_HOLD_MS = 700;

/**
 * Holds submissions that have already been reflected in the UI.
 *
 * The optimistic state is a *prediction* of what the server will accept, never
 * the source of truth: an entry that exhausts its retries is rolled back and
 * the card restored, because a grade the server rejected did not happen. The
 * request id travels with the entry so a retry is idempotent server-side
 * rather than a second attempt.
 */
export class SubmissionOutbox<T> {
  #entries = $state<OutboxEntry<T>[]>([]);
  // SvelteMap rather than Map only because the project lints for it; these are
  // timer handles, and nothing renders from them.
  #holds = new SvelteMap<string, ReturnType<typeof setTimeout>>();
  #options: OutboxOptions<T>;

  constructor(options: OutboxOptions<T>) {
    this.#options = options;
  }

  get entries(): OutboxEntry<T>[] {
    return this.#entries;
  }

  get pendingCount(): number {
    return this.#entries.filter((entry) => entry.status !== "failed").length;
  }

  get failedCount(): number {
    return this.#entries.filter((entry) => entry.status === "failed").length;
  }

  has(requestId: string): boolean {
    return this.#entries.some((entry) => entry.requestId === requestId);
  }

  /** Cancel a submission that has not been sent yet; returns whether it was. */
  cancel(requestId: string): boolean {
    const entry = this.#entries.find((item) => item.requestId === requestId);
    if (!entry || entry.attempts > 0) {
      return false;
    }
    this.#clearHold(requestId);
    this.#remove(requestId);
    return true;
  }

  /**
   * Take a grade, and send it once its cancel window closes.
   *
   * Resolves when the entry is queued, not when it is accepted: the learner is
   * already looking at the next card, and blocking on the network here is what
   * the outbox exists to avoid.
   */
  enqueue(requestId: string, payload: T): void {
    const entry: OutboxEntry<T> = {
      requestId,
      payload,
      status: "pending",
      attempts: 0,
    };
    this.#entries.push(entry);
    // Work with the entry the state array owns, not the literal above: writes
    // to a captured plain object do not reliably reach the reactive copy, and
    // a status the UI never sees is a grade the learner cannot retry.
    const stored = this.#entries[this.#entries.length - 1] ?? entry;

    const holdMs = this.#options.holdMs ?? DEFAULT_HOLD_MS;
    if (holdMs <= 0) {
      void this.#send(stored);
      return;
    }
    this.#holds.set(
      requestId,
      setTimeout(() => {
        this.#holds.delete(requestId);
        void this.#send(stored);
      }, holdMs),
    );
  }

  /**
   * Send everything still being held, now.
   *
   * Called when the surface is torn down: a held grade is a real grade, and a
   * learner closing the tab must not lose it to a cancel window nobody used.
   */
  flush(): void {
    for (const entry of this.#entries) {
      if (this.#holds.has(entry.requestId)) {
        this.#clearHold(entry.requestId);
        void this.#send(entry);
      }
    }
  }

  async retry(requestId: string): Promise<void> {
    const entry = this.#entries.find((item) => item.requestId === requestId);
    if (!entry) {
      return;
    }
    entry.status = "retrying";
    await this.#send(entry);
  }

  async #send(entry: OutboxEntry<T>): Promise<void> {
    const maxAttempts = this.#options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    const wait = this.#options.wait ?? defaultWait;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      entry.attempts += 1;
      try {
        await this.#options.submit(entry.payload, entry.requestId);
        this.#remove(entry.requestId);
        return;
      } catch (error) {
        if (!isRetryable(error) || attempt === maxAttempts) {
          entry.status = "failed";
          this.#options.rollback(entry, error);
          return;
        }
        entry.status = "retrying";
        await wait(
          (this.#options.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS) * attempt,
        );
      }
    }
  }

  #clearHold(requestId: string): void {
    const hold = this.#holds.get(requestId);
    if (hold !== undefined) {
      clearTimeout(hold);
      this.#holds.delete(requestId);
    }
  }

  #remove(requestId: string): void {
    this.#entries = this.#entries.filter(
      (entry) => entry.requestId !== requestId,
    );
  }
}

function isRetryable(error: unknown): boolean {
  if (error instanceof SophiaApiError) {
    return isRetryableFailure({
      detail: error.detail,
      requestId: error.requestId,
      status: error.status,
    });
  }
  // A thrown TypeError is how fetch reports "the network did not answer",
  // which is exactly the case worth retrying.
  return error instanceof TypeError;
}

function defaultWait(delayMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}
