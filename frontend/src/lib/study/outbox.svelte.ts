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
  wait?: (delayMs: number) => Promise<void>;
};

export const DEFAULT_MAX_ATTEMPTS = 3;
export const DEFAULT_RETRY_DELAY_MS = 400;

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
    this.#remove(requestId);
    return true;
  }

  async enqueue(requestId: string, payload: T): Promise<void> {
    const entry: OutboxEntry<T> = {
      requestId,
      payload,
      status: "pending",
      attempts: 0,
    };
    this.#entries.push(entry);
    await this.#send(entry);
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
