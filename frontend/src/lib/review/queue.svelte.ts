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
   * Retry tuning. The shipping default never resends on its own: unlike a
   * study attempt, `/api/review/complete` carries no request id, so a resend
   * the server already accepted would advance the schedule a second time. A
   * rejected review rolls back and offers the learner a button, and that
   * button is bounded too — see `REVIEW_MAX_SENDS`.
   */
  retry?: Pick<
    OutboxOptions<ReviewSubmission>,
    "maxAttempts" | "maxSends" | "retryDelayMs" | "holdMs" | "wait"
  >;
  now?: () => number;
  newId?: () => string;
};

/** No automatic resend: the loop runs once and then reports failure. */
export const REVIEW_MAX_SEND_ATTEMPTS = 1;

/**
 * Sends per submission, the learner's own retries included.
 *
 * One automatic, two deliberate. Per *submission*, not per topic: grading a
 * rolled-back card again is a new submission and starts a fresh count, which
 * is right — the learner deliberately re-answered. `sending` is what stops the
 * two overlapping.
 *
 * A retry only reaches the server after the previous send reported failure, so
 * the dangerous case is narrow: a request the server committed and the browser
 * never saw the answer to. This cannot close that hole, only keep it from
 * repeating. Closing it means a request id on the endpoint, which means a
 * persisted uniqueness constraint that is not this phase's to add.
 */
export const REVIEW_MAX_SENDS = 3;

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
  /**
   * Queue positions the server has taken.
   *
   * The outbox drops an entry once it is accepted, which makes "accepted" and
   * "cancelled" look identical afterwards. Without this record the queue
   * cannot tell that a card behind the cursor is already durable, and both
   * recovery paths — a successful manual retry, and a rollback rewinding over
   * a neighbour that succeeded — put that card back in front of the learner to
   * be graded a second time.
   */
  #accepted = $state<number[]>([]);
  #promptShownAt = $state(0);
  #clockMs = $state(0);
  #lastGrade = $state<{ requestId: string; position: number } | null>(null);
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
      maxSends: REVIEW_MAX_SENDS,
      ...options.retry,
      onAccepted: (entry) => this.#accept(entry.payload.queuePosition),
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

  /**
   * Reviews this sitting has put through.
   *
   * Derived rather than counted by hand: what the server has taken, plus what
   * is still on its way. A rejected review is in neither, which is the point —
   * the old hand-incremented counter could disagree with the outbox after a
   * rollback and tell the learner they had reviewed something they had not.
   */
  get gradedCount(): number {
    return this.#accepted.length + this.#outbox.pendingCount;
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
    return (
      this.#lastGrade !== null &&
      this.#outbox.canCancel(this.#lastGrade.requestId)
    );
  }

  /** Whether this rejected review may be sent again; see `REVIEW_MAX_SENDS`. */
  canRetry(requestId: string): boolean {
    return this.#outbox.canRetry(requestId);
  }

  /**
   * Whether a submission for the card in front of the learner is on the wire.
   *
   * True during a manual retry, when the outbox has taken the retry button
   * away — a rolled-back card is revealed, so the grade bar is showing with
   * nothing to say that anything is happening. Grading it then would enqueue a
   * second submission for the same topic, and the endpoint has no request id
   * to fold the two together.
   */
  get sending(): boolean {
    return this.#hasSubmissionAt(this.#index);
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
    // `discardFailed` below only supersedes a *rejected* submission. One still
    // in flight has to block the grade outright: both would reach the server,
    // and it cannot tell they are the same review.
    if (this.#hasSubmissionAt(position)) {
      return false;
    }

    const requestId = this.#newId();
    this.#outbox.discardFailed(
      (failed) => failed.payload.queuePosition === position,
    );
    this.#lastGrade = { position, requestId };
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
    const grade = this.#lastGrade;
    if (grade === null || !this.#outbox.cancel(grade.requestId)) {
      return false;
    }
    this.#lastGrade = null;
    // Back to the card that grade belonged to, not one step back: a card the
    // server accepted while this one was held may have moved the cursor
    // further than a single position.
    this.#index = grade.position;
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

  #hasSubmissionAt(position: number): boolean {
    return this.#outbox.entries.some(
      (entry) =>
        entry.payload.queuePosition === position && entry.status !== "failed",
    );
  }

  #accept(position: number): void {
    if (!this.#accepted.includes(position)) {
      this.#accepted.push(position);
    }
    // A retry that succeeds has to move the queue on. Without this the card
    // the server just took is still the current one, revealed, with the grade
    // bar showing — and grading it again is the obvious next action.
    this.#seek();
  }

  #advance(): void {
    this.#index += 1;
    this.#restartPrompt();
    this.#seek();
  }

  /** Step over any card the server already holds. */
  #seek(): void {
    const before = this.#index;
    while (
      this.#index < this.#cards.length &&
      this.#accepted.includes(this.#index)
    ) {
      this.#index += 1;
    }
    if (this.#index !== before) {
      this.#restartPrompt();
    }
  }

  #restartPrompt(): void {
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
  }

  #rollback(entry: OutboxEntry<ReviewSubmission>): void {
    const card = this.#cards[entry.payload.queuePosition];
    if (card) {
      card.revealed = true;
    }
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
    // The rewind may have passed over a neighbour the server accepted in the
    // meantime; seeking again is what stops that one being graded twice.
    this.#seek();
    this.#error = "review.grade_rejected";
  }
}
