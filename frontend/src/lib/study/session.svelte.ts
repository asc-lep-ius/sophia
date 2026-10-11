import type {
  StudyAttemptPhase,
  StudyPacing,
  StudyQuestion,
} from "$lib/api/study";
import type { DraftStore } from "$lib/study/drafts";
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
  | "confidence"
  | "revealed"
  | "grading"
  | "committed"
  | "flagged"
  | "rollback"
  | "paused";

export type StudyCard = {
  question: StudyQuestion;
  answer: string;
  revealed: boolean;
  /** How sure the learner said they were, asked before the reveal; null until then. */
  confidence: Confidence | null;
  /** How many times the card has come back after an Again: 0 on first sight. */
  retry: number;
};

/** A card graded Again that has yet to come back. */
export type RequeuedCard = {
  question: StudyQuestion;
  retry: number;
};

/**
 * Which grade queued a re-ask: undoing or losing that grade takes the re-ask
 * back with it. `null` for one read back from the server on resume, whose
 * grade is already durable.
 */
type QueuedBy = { queuedBy: string | null };

export type GradeSubmission = {
  questionId: string;
  answerText: string;
  selfRating: number;
  confidence: Confidence | null;
  phase: StudyAttemptPhase;
  queuePosition: number;
  retry: number;
};

export type StudySessionStoreOptions = {
  questions: StudyQuestion[];
  pacing: StudyPacing;
  phase?: StudyAttemptPhase;
  /**
   * Practice cards graded Again in an earlier visit and still owed a re-ask,
   * as the server counts them; they come after every card in `questions`.
   */
  requeued?: RequeuedCard[];
  submit: (submission: GradeSubmission, requestId: string) => Promise<void>;
  learningEvents?: Pick<LearningEventBatcher, "record">;
  /** Answers in progress, keyed by question and re-ask, kept beyond this store. */
  drafts?: DraftStore;
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
const AGAIN: Grade = 1;
const HARD: Grade = 2;

/**
 * Guessing … Certain, the 1–5 scale an attempt's confidence is stored on.
 *
 * Asked per card, after the answer is written and before it is revealed: a
 * judgement made with the answer in view is inflated (Koriat & Bjork 2005),
 * and one made before the correction is what lets a confident error be told
 * apart from a guess (Butterfield & Metcalfe 2001).
 */
export const CONFIDENCES = [1, 2, 3, 4, 5] as const;
export type Confidence = (typeof CONFIDENCES)[number];

/**
 * Sure or Certain: a card answered this sure and graded Again or Hard is
 * flagged. Mirrors `SURE_CONFIDENCE` in `services/card_confidence.py`, which
 * counts the same answers on /app/calibration.
 */
export const SURE_CONFIDENCE: Confidence = 4;

/**
 * How many times one practice card may come back after an Again in a session.
 *
 * Mirrors `AGAIN_REASK_LIMIT` in `services/study_questions.py`, which counts a
 * resumed session's owed re-asks against the same number. A failed card is
 * cycled until it is recalled once, but capped, or the hardest card eats the
 * session.
 */
export const AGAIN_REASK_LIMIT = 2;

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
  /** Every card in order, with each re-ask appended once it is called in. */
  #cards = $state<(StudyCard & QueuedBy)[]>([]);
  /**
   * Re-asks waiting behind every card still to come, oldest first.
   *
   * Called into `#cards` only once the learner has reached the end of it, so
   * whatever else remains always comes between a grade and its re-ask, and a
   * grade taken back can take its re-ask back without moving any card that
   * an outbox entry points at.
   */
  #owed = $state<(RequeuedCard & QueuedBy)[]>([]);
  #index = $state(0);
  #state = $state<StudyState>("idle");
  #stateBeforePause: StudyState = "prompt";
  #promptShownAt = $state(0);
  #clockMs = $state(0);
  #lastGrade = $state<{
    requestId: string;
    at: number;
    position: number;
  } | null>(null);
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
    this.#cards = options.questions.map((question) =>
      this.#card({ question, retry: 0, queuedBy: null }),
    );
    this.#owed = (options.requeued ?? []).map((card) => ({
      ...card,
      queuedBy: null,
    }));
    this.#callInReask();
    this.#state = this.#cards.length > 0 ? "prompt" : "idle";
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
    this.#outbox = new SubmissionOutbox<GradeSubmission>({
      ...options.retry,
      submit: async (payload, requestId) => {
        await this.#options.submit(payload, requestId);
        // Only once the server has it: a grade that is refused or never
        // lands leaves the card to be answered again, text and all.
        this.#options.drafts?.clear(
          draftKey(payload.questionId, payload.retry),
        );
      },
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
    return this.#cards.length + this.#owed.length;
  }

  get remaining(): number {
    return Math.max(this.total - this.#index, 0);
  }

  /**
   * Re-asks still to come: those waiting behind the queue, and any a rewind
   * has left ahead of the learner. A card graded Again at the cap is not one —
   * the indicator promises a re-ask, so it counts only the ones that will happen.
   */
  get againLaterCount(): number {
    const ahead = this.#cards
      .slice(this.#index + 1)
      .filter((card) => card.retry > 0).length;
    return this.#owed.length + ahead;
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
    // #clockMs is read to make everything downstream reactive; the value comes
    // from the clock itself, so a tick delayed by a loaded machine reports a
    // late-but-true dwell rather than a short one.
    return Math.max(this.#clockMs, this.#now(), this.#promptShownAt);
  }

  /**
   * Whether the server would currently accept an answer for this card.
   *
   * Mirrored from the policy the question carries so the surface can say what
   * is still missing; the server checks the learner's own event trace either
   * way, and a client that lies here only earns a 412.
   */
  get canReveal(): boolean {
    return this.#state === "prompt" && this.#floorsMet();
  }

  /** Whether the learner has asked to reveal and is being asked how sure they are. */
  get askingConfidence(): boolean {
    const state =
      this.#state === "paused" ? this.#stateBeforePause : this.#state;
    return state === "confidence";
  }

  /** Whether a confidence chosen now would reveal the card. */
  get canChooseConfidence(): boolean {
    return this.#state === "confidence" && this.#floorsMet();
  }

  #floorsMet(): boolean {
    return (
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

  /**
   * Whether the card just graded was one the learner was sure of and graded
   * Again or Hard, and is held on screen until they move on.
   */
  get flagged(): boolean {
    const state =
      this.#state === "paused" ? this.#stateBeforePause : this.#state;
    return state === "flagged";
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
    this.#options.drafts?.write(draftKey(card.question.id, card.retry), value);
    this.#options.learningEvents?.record({
      eventType: "elaboration_written",
      questionId: card.question.id,
      payload: { text_length: value.trim().length },
    });
  }

  /**
   * The learner pressed Reveal: ask how sure they are before showing anything.
   *
   * The reveal itself waits for `reveal(confidence)`, so no card is ever shown
   * without a confidence committed first.
   */
  askConfidence(): boolean {
    if (!this.canReveal) {
      return false;
    }
    this.#state = "confidence";
    return true;
  }

  reveal(confidence: Confidence): boolean {
    if (!this.canChooseConfidence) {
      return false;
    }
    const card = this.current;
    if (!card) {
      return false;
    }
    card.confidence = confidence;
    card.revealed = true;
    this.#state = "revealed";
    // canReveal already required dwellMs to clear the policy's floor, so this
    // is where the server's engagement check gets a prompt_shown worth
    // trusting: the mount-time one from recordPromptShown carries a near-zero
    // dwell, and the server takes the max it has seen for the question.
    this.#options.learningEvents?.record({
      eventType: "prompt_shown",
      questionId: card.question.id,
      payload: { dwell_ms: this.dwellMs },
    });
    this.#options.learningEvents?.record({
      eventType: "answer_revealed",
      questionId: card.question.id,
    });
    return true;
  }

  grade(rating: Grade): boolean {
    const card = this.current;
    if (!card || !this.canGrade) {
      return false;
    }

    const position = this.#index;
    const submission: GradeSubmission = {
      questionId: card.question.id,
      answerText: card.answer,
      selfRating: rating,
      confidence: card.confidence,
      phase: this.#phase,
      queuePosition: position,
      retry: card.retry,
    };
    const requestId = this.#newId();

    // This submission supersedes any rejected one for the same card: see
    // SubmissionOutbox.discardFailed for what leaving it behind would cost.
    this.#outbox.discardFailed(
      (failed) => failed.payload.queuePosition === position,
    );

    // Optimistic: the learner sees the next card immediately, and the entry
    // holds everything needed to put this one back if the server refuses.
    if (rating === AGAIN) {
      this.#requeue(card, requestId);
    }
    this.#lastGrade = { requestId, at: this.#now(), position };
    if (isSureMiss(card, rating)) {
      // Held, not advanced: a confident error is the one most worth looking
      // at while the correction is still on screen (Butterfield & Metcalfe
      // 2001). The grade goes out as any other; only the next card waits.
      this.#state = "flagged";
    } else {
      this.#state = "committed";
      this.#advance();
    }

    this.#outbox.enqueue(requestId, submission);
    return true;
  }

  /** Leave a flagged card for the next one. */
  moveOn(): boolean {
    if (this.#state !== "flagged") {
      return false;
    }
    this.#advance();
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
    this.#withdrawReask(grade.requestId);
    this.#index = grade.position;
    const card = this.current;
    if (card) {
      card.revealed = true;
    }
    this.#state = "revealed";
    return true;
  }

  /** Whether the outbox would take another send for this rejected grade. */
  canRetry(requestId: string): boolean {
    return this.#outbox.canRetry(requestId);
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

  /**
   * Mark that the prompt is on screen, for the server's required-events check.
   *
   * Reads `#now()` and `#promptShownAt` directly rather than `dwellMs`: that
   * getter goes through `#observedNow()`, which reads the reactive `#clockMs`
   * tick so `canReveal` stays live. A caller inside an `$effect` that read
   * `dwellMs` here would re-run on every 250ms tick, tearing down and
   * rebuilding the batcher along with it.
   *
   * The page's effect still re-runs this whenever the card on screen changes
   * — at mount, after each grade advances the queue, and on `resume()` — and
   * each later card's `prompt_shown` depends on that. Its dwell is therefore
   * always near zero: it is `reveal()`'s own `prompt_shown` record that
   * carries a dwell able to clear the pacing floor, since the server takes the
   * highest one it has seen for the question. Keep that record — without it
   * the server never sees a dwell above zero.
   */
  recordPromptShown(): void {
    const card = this.current;
    if (!card) {
      return;
    }
    this.#options.learningEvents?.record({
      eventType: "prompt_shown",
      questionId: card.question.id,
      payload: { dwell_ms: Math.max(this.#now() - this.#promptShownAt, 0) },
    });
  }

  get #phase(): StudyAttemptPhase {
    return this.#options.phase ?? "practice";
  }

  #card(card: RequeuedCard & QueuedBy): StudyCard & QueuedBy {
    // A re-ask starts empty — the learner retrieves again rather than reading
    // their failed answer back — and keeps a draft of its own, so the first
    // answer's draft cannot be offered back on the second presentation.
    const draft = this.#options.drafts?.read(
      draftKey(card.question.id, card.retry),
    );
    return { ...card, answer: draft ?? "", revealed: false, confidence: null };
  }

  /**
   * Queue a card graded Again to come back after everything else.
   *
   * Only in practice: the pre-test and post-test are measurements, and an
   * Again there is the result. The cap reads the furthest re-ask this store
   * knows of for the question, not only the graded card's own count, so a
   * card regraded after a rollback cannot win itself an extra one.
   */
  #requeue(card: StudyCard, requestId: string): void {
    if (this.#phase !== "practice") {
      return;
    }
    const { question } = card;
    const retry =
      Math.max(
        card.retry,
        ...[...this.#cards, ...this.#owed]
          .filter((known) => known.question.id === question.id)
          .map((known) => known.retry),
      ) + 1;
    if (retry > AGAIN_REASK_LIMIT) {
      return;
    }
    this.#owed.push({ question, retry, queuedBy: requestId });
  }

  /** Bring the oldest owed re-ask in once the learner has reached the end. */
  #callInReask(): void {
    const next = this.#owed[0];
    if (next === undefined || this.#index < this.#cards.length) {
      return;
    }
    this.#owed.shift();
    this.#cards.push(this.#card(next));
  }

  /**
   * Take back the re-ask a grade queued, when that grade is taken back.
   *
   * One still owed simply goes. One already called in goes only while it is
   * the last card and the learner has not got past it — removing anything
   * else would shift the queue positions outbox entries point at. Past that
   * point it stays, and the cap in `#requeue` still bounds the card.
   */
  #withdrawReask(requestId: string): void {
    const owed = this.#owed.findIndex((card) => card.queuedBy === requestId);
    if (owed >= 0) {
      this.#owed.splice(owed, 1);
      return;
    }
    const last = this.#cards.length - 1;
    if (
      this.#cards[last]?.queuedBy === requestId &&
      this.#index <= last &&
      !this.#outbox.entries.some(
        (entry) => entry.payload.queuePosition === last,
      )
    ) {
      this.#cards.pop();
    }
  }

  #advance(): void {
    this.#index += 1;
    this.#callInReask();
    if (this.#index >= this.#cards.length) {
      this.#index = this.#cards.length;
      this.#state = "idle";
      return;
    }
    this.#promptShownAt = this.#now();
    this.#clockMs = this.#promptShownAt;
    this.#state = "prompt";
  }

  #rollback(entry: OutboxEntry<GradeSubmission>): void {
    const card = this.#cards[entry.payload.queuePosition];
    if (card) {
      card.revealed = true;
    }
    this.#withdrawReask(entry.requestId);

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

function isSureMiss(card: StudyCard, rating: Grade): boolean {
  return (
    rating <= HARD &&
    card.confidence !== null &&
    card.confidence >= SURE_CONFIDENCE
  );
}

/**
 * Where a card's unsent answer is kept.
 *
 * A first presentation keeps the bare question id, as drafts always have; a
 * re-ask gets its own key, so the first answer, still waiting for the server
 * to take it, is never offered back as the second.
 */
function draftKey(questionId: string, retry: number): string {
  return retry === 0 ? questionId : `${questionId}#retry-${retry}`;
}
