import type { StudySessionItem } from "$lib/dashboard/panels";

export type NextAction =
  | { kind: "review"; count: number }
  | { kind: "resume"; sessionId: number; topic: string }
  | { kind: "study" }
  | { kind: "quickstart" };

export type NextActionInput = {
  dueReviewCount: number;
  sessions: StudySessionItem[];
};

/**
 * The one thing worth doing next.
 *
 * A dashboard that ranks nothing leaves the learner to rank it, which is the
 * decision they came here to have made. The order is pedagogical, not
 * cosmetic: a review that is due has a forgetting curve behind it and stops
 * being worth as much every day it waits, so it outranks new work. An
 * unfinished session comes next, because leaving it open costs the pre/post
 * comparison it was started for.
 */
export function nextAction(input: NextActionInput): NextAction {
  const open = openSession(input.sessions);
  if (input.dueReviewCount > 0) {
    return { kind: "review", count: input.dueReviewCount };
  }
  if (open) {
    return { kind: "resume", sessionId: open.id, topic: open.topic };
  }
  return input.sessions.length === 0
    ? { kind: "quickstart" }
    : { kind: "study" };
}

function openSession(
  sessions: StudySessionItem[],
): StudySessionItem | undefined {
  return sessions.find((session) => session.completed_at === null);
}
