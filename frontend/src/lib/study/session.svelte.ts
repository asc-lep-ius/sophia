import type {
  StudyAttemptPhase,
  StudyPacing,
  StudyQuestion,
} from "$lib/api/study";
import type { LearningEventBatcher } from "$lib/study/learningEvents";
import {
  SubmissionOutbox,
  type OutboxEntry,
  type OutboxOptions,
} from "$lib/study/outbox.svelte";
import { enforcedPolicy } from "$lib/study/policy";

export type StudyState =
  | "idle"
  | "loading"
  | "prompt"
  | "revealed"
  | "grading"
  | "committed"
  | "rollback"
  | "paused";

export type StudyCard = {
  question: StudyQuestion;
  answer: string;
  revealed: boolean;
  againLater: boolean;
};

export type GradeSubmission = {
  questionId: string;
  answerText: string;
  selfRating: number;
  confidence: number | null;
  phase: StudyAttemptPhase;
  queuePosition: number;
};

export type StudySessionStoreOptions = {
  questions: StudyQuestion[];
  pacing: StudyPacing;
  phase?: StudyAttemptPhase;
  submit: (submission: GradeSubmission, requestId: string) => Promise<void>;
  learningEvents?: Pick<LearningEventBatcher, "record">;
  /** Retry tuning for the grade outbox; the defaults are the shipping ones. */
  retry?: Pick<
    OutboxOptions<GradeSubmission>,
    "maxAttempts" | "retryDelayMs" | "holdMs" | "wait"
  >;
  now?: () => number;
  newId?: () => string;
};

/** Again/Hard/Good/Easy, the same scale the server grades an attempt on. */
export const GRADES = [1, 2, 3, 4] as const;
export type Grade = (typeof GRADES)[number];

/**
 * The study session's state machine and card queue.
 *
 * A class instantiated by the route, not module-level `$state`: module-level
 * runes are shared across SSR requests, which would leak one learner's session
 * into another's render.
 *
 * Nothing here decides a score. A grade is the learner's own post-reveal
 * self-rating, sent as-is; what it is worth is the server's to say.
 */
export class StudySessionStore {
  #cards = $state<StudyCard[]>([]);
  #index = $state(0);
  #state = $state<StudyState>("idle");
  #stateBeforePause: StudyState = "prompt";
  #promptShownAt = $state(0);
  #clockMs = $state(0);
  #lastGrade = $state<{ requestId: string; at: number } | null>(null);
  #error = $state<string | null>(null);
  #focusMode = $state(false);
  #options: StudySessionStoreOptions;
  #outbox: SubmissionOutbox<GradeSubmission>;
  #now: () => number;
  #newId: () => string;

  constructor(options: StudySessionStoreOptions) {
    this.#options = options;
    this.#now = options.now ?? (() => Date.now());
    this.#newId = options.newId ?? (() => crypto.randomUUID());
    this.#cards = options.questions.map((question) => ({
      question,
      answer: "",
      revealed: false,
      againLater: false,
    }));
    this.#state = this.#cards.length > 0 ? "prompt" : "idle";
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
    this.#outbox = new SubmissionOutbox<GradeSubmission>({
      ...options.retry,
      submit: (payload, requestId) => this.#options.submit(payload, requestId),
      rollback: (entry) => this.#rollback(entry),
    });
  }

  get state(): StudyState {
    return this.#state;
  }

  get cards(): StudyCard[] {
    return this.#cards;
  }

  get current(): StudyCard | null {
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

  get againLaterCount(): number {
    return this.#cards.filter((card) => card.againLater).length;
  }

  get pendingCount(): number {
    return this.#outbox.pendingCount;
  }

  /** Grades the server refused and never took. */
  get failedCount(): number {
    return this.#outbox.failedCount;
  }

  get outboxEntries(): OutboxEntry<GradeSubmission>[] {
    return this.#outbox.entries;
  }

  get error(): string | null {
    return this.#error;
  }

  get focusMode(): boolean {
    return this.#focusMode;
  }

  get paused(): boolean {
    return this.#state === "paused";
  }

  get answer(): string {
    return this.current?.answer ?? "";
  }

  get elaborationChars(): number {
    return this.answer.trim().length;
  }

  get dwellMs(): number {
    return this.#observedNow() - this.#promptShownAt;
  }

  /**
   * Advance the store's view of the clock.
   *
   * Time is state here, not something read at render: whether the dwell floor
   * has passed changes with nothing else on the page, so without a tick the
   * reveal button would stay disabled until the learner happened to type
   * another character.
   */
  tick(): void {
    this.#clockMs = this.#now();
  }

  #observedNow(): number {
    return Math.max(this.#clockMs, this.#promptShownAt);
  }

  /**
   * Whether the server would currently accept an answer for this card.
   *
   * Mirrored from the policy the question carries so the surface can say what
   * is still missing; the server checks the learner's own event trace either
   * way, and a client that lies here only earns a 412.
   */
  get canReveal(): boolean {
    return (
      this.#state === "prompt" &&
      this.elaborationChars >= this.minElaborationChars &&
      this.dwellMs >= this.minPromptDwellMs
    );
  }

  get minElaborationChars(): number {
    return this.#policy().minElaborationChars;
  }

  get minPromptDwellMs(): number {
    return this.#policy().minPromptDwellMs;
  }

  #policy(): { minElaborationChars: number; minPromptDwellMs: number } {
    const card = this.current;
    if (!card) {
      return {
        minElaborationChars: this.#options.pacing.elaboration_min_chars,
        minPromptDwellMs: this.#options.pacing.prompt_min_dwell_ms,
      };
    }
    return enforcedPolicy(card.question, this.#options.pacing);
  }

  get canGrade(): boolean {
    // "rollback" is here because a restored card is a revealed card waiting for
    // another grade: leaving it out meant a rejected grade could never be
    // retried by the learner, only by the outbox.
    return (
      this.#state === "revealed" ||
      this.#state === "grading" ||
      this.#state === "rollback"
    );
  }

  /**
   * Whether the last grade can still be taken back.
   *
   * Asks the outbox rather than a wall clock: a button that stays enabled
   * after the grade has gone can only ever apologise, which is worse than a
   * button that goes quiet at the moment the answer becomes "no".
   */
  get canUndo(): boolean {
    const grade = this.#lastGrade;
    return grade !== null && this.#outbox.canCancel(grade.requestId);
  }

  setAnswer(value: string): void {
    const card = this.current;
    if (!card || this.#state === "paused") {
      return;
    }
    card.answer = value;
    this.#options.learningEvents?.record({
      eventType: "elaboration_written",
      questionId: card.question.id,
      payload: { text_length: value.trim().length },
    });
  }

  reveal(): boolean {
    if (!this.canReveal) {
      return false;
    }
    const card = this.current;
    if (!card) {
      return false;
    }
    card.revealed = true;
    this.#state = "revealed";
    this.#options.learningEvents?.record({
      eventType: "answer_revealed",
      questionId: card.question.id,
    });
    return true;
  }

  grade(rating: Grade, confidence: number | null = null): boolean {
    const card = this.current;
    if (!card || !this.canGrade) {
      return false;
    }

    const submission: GradeSubmission = {
      questionId: card.question.id,
      answerText: card.answer,
      selfRating: rating,
      confidence,
      phase: this.#options.phase ?? "practice",
      queuePosition: this.#index,
    };
    const requestId = this.#newId();

    // This submission supersedes any rejected one for the same card: see
    // SubmissionOutbox.discardFailed for what leaving it behind would cost.
    const position = this.#index;
    this.#outbox.discardFailed(
      (failed) => failed.payload.queuePosition === position,
    );

    // Optimistic: the learner sees the next card immediately, and the entry
    // holds everything needed to put this one back if the server refuses.
    card.againLater = rating === 1;
    this.#state = "committed";
    this.#lastGrade = { requestId, at: this.#now() };
    this.#advance();

    this.#outbox.enqueue(requestId, submission);
    return true;
  }

  /** Send anything still inside its cancel window — the surface is going away. */
  flushGrades(): void {
    this.#outbox.flush();
  }

  /**
   * Cancel the last grade if it is still in the outbox.
   *
   * A grade the server has already accepted is not undone here: it is durable,
   * and pretending otherwise would show the learner a queue the server does
   * not have.
   */
  undo(): boolean {
    const grade = this.#lastGrade;
    if (!grade || !this.canUndo) {
      return false;
    }
    if (!this.#outbox.cancel(grade.requestId)) {
      this.#error = "study.undo_already_committed";
      return false;
    }
    this.#lastGrade = null;
    this.#index = Math.max(this.#index - 1, 0);
    const card = this.current;
    if (card) {
      card.revealed = true;
      card.againLater = false;
    }
    this.#state = "revealed";
    return true;
  }

  retryFailed(requestId: string): Promise<void> {
    this.#error = null;
    return this.#outbox.retry(requestId);
  }

  pause(): void {
    if (this.#state === "paused") {
      return;
    }
    this.#stateBeforePause = this.#state;
    this.#state = "paused";
  }

  resume(): void {
    if (this.#state !== "paused") {
      return;
    }
    this.#state = this.#stateBeforePause;
    // The clock restarts rather than counting the pause as engagement: a
    // paused session is not a learner sitting with the prompt.
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
  }

  togglePause(): void {
    if (this.#state === "paused") {
      this.resume();
      return;
    }
    this.pause();
  }

  toggleFocusMode(): void {
    this.#focusMode = !this.#focusMode;
  }

  dismissError(): void {
    this.#error = null;
  }

  /** Report how long the prompt has been on screen, for the server's policy. */
  recordPromptShown(): void {
    const card = this.current;
    if (!card) {
      return;
    }
    this.#options.learningEvents?.record({
      eventType: "prompt_shown",
      questionId: card.question.id,
      payload: { dwell_ms: this.dwellMs },
    });
  }

  #advance(): void {
    if (this.#index >= this.#cards.length - 1) {
      this.#index = this.#cards.length;
      this.#state = "idle";
      return;
    }
    this.#index += 1;
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
    this.#state = "prompt";
  }

  #rollback(entry: OutboxEntry<GradeSubmission>): void {
    const card = this.#cards[entry.payload.queuePosition];
    if (card) {
      card.revealed = true;
      card.againLater = false;
    }

    // Rewind to the earliest rejected card, never simply to this one: with
    // several grades in flight a later rollback would otherwise overwrite an
    // earlier one's restoration and quietly drop it. Rewinding is also only
    // ever backwards — a rollback that arrives while the learner is further on
    // must not drag them forwards.
    const earliestRejected = Math.min(
      ...this.#outbox.entries
        .filter((failed) => failed.status === "failed")
        .map((failed) => failed.payload.queuePosition),
      entry.payload.queuePosition,
    );
    this.#index = Math.min(this.#index, earliestRejected);
    this.#state = "rollback";
    this.#error = "study.grade_rejected";
  }
}
