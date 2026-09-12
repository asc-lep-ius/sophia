import {
  SubmissionOutbox,
  type OutboxEntry,
  type OutboxOptions,
} from "$lib/study/outbox.svelte";
import type { Grade } from "$lib/study/session.svelte";

export type ReviewCard = {
  topic: string;
  recall: string;
  revealed: boolean;
};

export type ReviewSubmission = {
  topic: string;
  recallText: string;
  selfRating: Grade;
  queuePosition: number;
};

export type ReviewPacing = {
  minRecallChars: number;
  minPromptDwellMs: number;
};

export type ReviewQueueOptions = {
  topics: string[];
  pacing: ReviewPacing;
  submit: (submission: ReviewSubmission, requestId: string) => Promise<void>;
  /**
   * Retry tuning. The shipping default sends once and no more: unlike a study
   * attempt, `/api/review/complete` carries no request id, so a retry the
   * server already accepted would advance the schedule a second time. A
   * rejected review rolls back and offers the learner a button instead.
   */
  retry?: Pick<
    OutboxOptions<ReviewSubmission>,
    "maxAttempts" | "retryDelayMs" | "holdMs" | "wait"
  >;
  now?: () => number;
  newId?: () => string;
};

export const REVIEW_MAX_SEND_ATTEMPTS = 1;

/**
 * The queue of topics due for review.
 *
 * A class the route instantiates, never module-level `$state`: module runes
 * are shared across SSR requests in one process, which would show one
 * learner's queue to the next.
 *
 * Nothing here scores a review or decides when the topic comes back. The
 * rating travels to the server as the button the learner pressed; the FSRS
 * parameters and the next date come back in the response. The grade scale
 * itself is `Grade` from the study session store — the same Again/Hard/Good/
 * Easy the study surface uses, not a second copy of it.
 */
export class ReviewQueueStore {
  #cards = $state<ReviewCard[]>([]);
  #index = $state(0);
  #graded = $state(0);
  #promptShownAt = $state(0);
  #clockMs = $state(0);
  #lastGrade = $state<string | null>(null);
  #error = $state<string | null>(null);
  #options: ReviewQueueOptions;
  #outbox: SubmissionOutbox<ReviewSubmission>;
  #now: () => number;
  #newId: () => string;

  constructor(options: ReviewQueueOptions) {
    this.#options = options;
    this.#now = options.now ?? (() => Date.now());
    this.#newId = options.newId ?? (() => crypto.randomUUID());
    this.#cards = options.topics.map((topic) => ({
      recall: "",
      revealed: false,
      topic,
    }));
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
    this.#outbox = new SubmissionOutbox<ReviewSubmission>({
      maxAttempts: REVIEW_MAX_SEND_ATTEMPTS,
      ...options.retry,
      rollback: (entry) => this.#rollback(entry),
      submit: (payload, requestId) => this.#options.submit(payload, requestId),
    });
  }

  get current(): ReviewCard | null {
    return this.#cards[this.#index] ?? null;
  }

  get position(): number {
    return this.#cards.length === 0 ? 0 : this.#index + 1;
  }

  get total(): number {
    return this.#cards.length;
  }

  get remaining(): number {
    return Math.max(this.#cards.length - this.#index, 0);
  }

  get gradedCount(): number {
    return this.#graded;
  }

  get finished(): boolean {
    return this.#cards.length > 0 && this.#index >= this.#cards.length;
  }

  get recall(): string {
    return this.current?.recall ?? "";
  }

  get minRecallChars(): number {
    return this.#options.pacing.minRecallChars;
  }

  get pendingCount(): number {
    return this.#outbox.pendingCount;
  }

  get failedCount(): number {
    return this.#outbox.failedCount;
  }

  get outboxEntries(): OutboxEntry<ReviewSubmission>[] {
    return this.#outbox.entries;
  }

  get error(): string | null {
    return this.#error;
  }

  /**
   * Whether the recall attempt has gone far enough to show the topic again.
   *
   * The floor is the same one the study surface enforces, read from
   * `/api/study/pacing`, not a second number invented here. Retrieval that is
   * skipped is not retrieval, and the pause is the point of the exercise.
   */
  get canReveal(): boolean {
    const card = this.current;
    if (!card || card.revealed) {
      return false;
    }
    return (
      card.recall.trim().length >= this.minRecallChars &&
      this.dwellMs >= this.#options.pacing.minPromptDwellMs
    );
  }

  get dwellMs(): number {
    return (
      Math.max(this.#clockMs, this.#now(), this.#promptShownAt) -
      this.#promptShownAt
    );
  }

  /** Whether the last grade is still inside its cancel window. */
  get canUndo(): boolean {
    return this.#lastGrade !== null && this.#outbox.canCancel(this.#lastGrade);
  }

  /** Advance the store's view of the clock so the dwell floor can expire. */
  tick(): void {
    this.#clockMs = this.#now();
  }

  setRecall(value: string): void {
    const card = this.current;
    if (card) {
      card.recall = value;
    }
  }

  reveal(): boolean {
    const card = this.current;
    if (!card || !this.canReveal) {
      return false;
    }
    card.revealed = true;
    return true;
  }

  grade(rating: Grade): boolean {
    const card = this.current;
    if (!card || !card.revealed) {
      return false;
    }

    const position = this.#index;
    const requestId = this.#newId();
    this.#outbox.discardFailed(
      (failed) => failed.payload.queuePosition === position,
    );
    this.#lastGrade = requestId;
    this.#graded += 1;
    this.#advance();
    this.#outbox.enqueue(requestId, {
      queuePosition: position,
      recallText: card.recall,
      selfRating: rating,
      topic: card.topic,
    });
    return true;
  }

  undo(): boolean {
    const requestId = this.#lastGrade;
    if (requestId === null || !this.#outbox.cancel(requestId)) {
      return false;
    }
    this.#lastGrade = null;
    this.#graded = Math.max(this.#graded - 1, 0);
    this.#index = Math.max(this.#index - 1, 0);
    const card = this.current;
    if (card) {
      card.revealed = true;
    }
    return true;
  }

  retryFailed(requestId: string): Promise<void> {
    this.#error = null;
    return this.#outbox.retry(requestId);
  }

  /** Send anything still held — the surface is going away. */
  flush(): void {
    this.#outbox.flush();
  }

  dismissError(): void {
    this.#error = null;
  }

  #advance(): void {
    this.#index += 1;
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
  }

  #rollback(entry: OutboxEntry<ReviewSubmission>): void {
    const card = this.#cards[entry.payload.queuePosition];
    if (card) {
      card.revealed = true;
    }
    this.#graded = Math.max(this.#graded - 1, 0);
    // Rewind only backwards, and only to the earliest rejected card: with two
    // reviews in flight a later rollback must not undo an earlier one's
    // restoration, and neither may drag a learner forwards.
    const earliestRejected = Math.min(
      ...this.#outbox.entries
        .filter((failed) => failed.status === "failed")
        .map((failed) => failed.payload.queuePosition),
      entry.payload.queuePosition,
    );
    this.#index = Math.min(this.#index, earliestRejected);
    this.#error = "review.grade_rejected";
  }
}
