import {
  submitAttempt,
  type StudyAttempt,
  type StudyAttemptPhase,
  type StudyPacing,
  type StudyQuestion,
} from "$lib/api/study";
import { LearningEventBatcher } from "$lib/study/learningEvents";
import { StudySessionStore } from "$lib/study/session.svelte";

export type StudyRuntimeOptions = {
  csrfToken: string;
  learningPathId: number;
  sessionId: number;
  questions: StudyQuestion[];
  pacing: StudyPacing;
  phase: StudyAttemptPhase;
  onGraded?: (attempt: StudyAttempt) => void;
};

export type StudyRuntime = {
  store: StudySessionStore;
  events: LearningEventBatcher;
  destroy: () => void;
  flushOnUnload: () => void;
  resumeFromUnload: () => void;
};

/**
 * Wire a card queue to the API for one leg of the cycle.
 *
 * The event flush is awaited *before* the attempt, not batched alongside it:
 * the server refuses an answer whose required process events it has not
 * ingested, so submitting first would earn a 412 the learner did nothing to
 * deserve.
 */
export function createStudyRuntime(options: StudyRuntimeOptions): StudyRuntime {
  const context = {
    csrfToken: options.csrfToken,
    learningPathId: options.learningPathId,
    sessionId: options.sessionId,
  };
  const events = new LearningEventBatcher(context);
  let unloading = false;

  const store = new StudySessionStore({
    questions: options.questions,
    pacing: options.pacing,
    phase: options.phase,
    learningEvents: events,
    submit: async (submission, requestId) => {
      await events.flushNow();
      const attempt = await submitAttempt(
        context,
        {
          questionId: submission.questionId,
          answerText: submission.answerText,
          confidence: submission.confidence,
          selfRating: submission.selfRating,
          phase: submission.phase,
          requestId,
        },
        { keepalive: unloading },
      );
      options.onGraded?.(attempt);
    },
  });

  return {
    store,
    events,
    destroy: () => {
      // The grade goes first: its own submission awaits the event flush, so
      // the trace the server checks is on its way before the attempt is. A
      // bare event flush follows for the case where nothing was held.
      store.flushGrades();
      events.flushQuietly();
      events.destroy();
    },
    /**
     * Undo an unload that turned out not to be one.
     *
     * `pagehide` also fires with `persisted: true` when a page enters the
     * bfcache, and a page restored from it goes on being used. Leaving the
     * flags set would send every later request with `keepalive`, which caps
     * in-flight bodies at 64 KB.
     */
    resumeFromUnload: () => {
      unloading = false;
      events.resumeFromUnload();
    },

    /**
     * Teardown for a page that is going away rather than navigating.
     *
     * `$effect` cleanup does not run on a tab close or a hard reload, so
     * without this the grade still inside its cancel window would simply be
     * dropped. Requests go out with `keepalive`; a browser may still refuse
     * to finish them, and a grade that does not land leaves the card without
     * an attempt, so the resumed session presents it again.
     */
    flushOnUnload: () => {
      unloading = true;
      // Before the grade flush, not after: flushGrades reaches submit
      // synchronously, submit calls events.flushNow(), and the drain reads the
      // keepalive flag when it starts. Setting it afterwards left the events
      // POST without keepalive — the browser cancelled it on unload, and the
      // attempt that awaits it was then never issued at all.
      events.flushOnUnload();
      store.flushGrades();
    },
  };
}
