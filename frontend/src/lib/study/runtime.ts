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

  const store = new StudySessionStore({
    questions: options.questions,
    pacing: options.pacing,
    phase: options.phase,
    learningEvents: events,
    submit: async (submission, requestId) => {
      await events.flushNow();
      const attempt = await submitAttempt(context, {
        questionId: submission.questionId,
        answerText: submission.answerText,
        confidence: submission.confidence,
        selfRating: submission.selfRating,
        phase: submission.phase,
        requestId,
      });
      options.onGraded?.(attempt);
    },
  });

  return {
    store,
    events,
    destroy: () => {
      // Order matters: a held grade is sent last so the process events it
      // depends on are already on their way — the server refuses an attempt
      // whose trace it has not ingested.
      events.flushQuietly();
      events.destroy();
      store.flushGrades();
    },
  };
}
