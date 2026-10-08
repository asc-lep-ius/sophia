import type { StudyQuestion, StudySessionSummary } from "$lib/api/study";
import { practiceCards, preTestAnswered } from "$lib/study/deck";

export const CYCLE_STEPS = ["predict", "act", "reflect"] as const;
export type CycleStep = (typeof CYCLE_STEPS)[number];

/**
 * What the session layout's load depends on.
 *
 * A step can finish without a navigation — the pre-test lands, the practice
 * deck drains, the session closes — and the layout keeps whatever it loaded
 * until something invalidates this.
 */
export const STUDY_PROGRESS = "study:progress";

export type CycleProgress = {
  completed: ReadonlySet<CycleStep>;
  reachable: ReadonlySet<CycleStep>;
};

export type ProgressRecord = {
  questions: StudyQuestion[];
  attemptedQuestionIds: string[];
  summary: Pick<StudySessionSummary, "session">;
};

/**
 * How far through the cycle this learner is, from what the server recorded.
 *
 * Nothing here is remembered by the page: a step is done when the server holds
 * the attempts that finish it. That already speaks for the learner's trace — a
 * pre-test attempt is only accepted once the session's prediction has been
 * ingested — so the progress survives a navigation, a reload and a second tab.
 *
 * Work opens with the pre-test, the same rule the act route's guard applies,
 * or a stepper link would bounce straight back. Reflect opens with Work: the
 * learner decides when they have practised enough, and the deck need not be
 * drained first. A completed step is always reachable.
 */
export function cycleProgress({
  questions,
  attemptedQuestionIds,
  summary,
}: ProgressRecord): CycleProgress {
  const completed = new Set<CycleStep>();
  if (preTestAnswered(questions, attemptedQuestionIds)) {
    completed.add("predict");
    if (practiceCards(questions, attemptedQuestionIds).length === 0) {
      completed.add("act");
    }
  }
  if (summary.session.completed_at !== null) {
    completed.add("reflect");
  }

  const reachable = new Set<CycleStep>(["predict", ...completed]);
  if (completed.has("predict")) {
    reachable.add("act");
    reachable.add("reflect");
  }
  return { completed, reachable };
}
