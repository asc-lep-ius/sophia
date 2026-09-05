import type { StudyQuestion } from "$lib/api/study";

/**
 * The cards a session still owes this learner.
 *
 * A resumed session must not re-present a card that already has an attempt:
 * grading it again mints a fresh request id, so the server stores a *second*
 * attempt and averages both into the phase means the reflect route reports.
 * The server is the one that knows what was answered — the ids come from
 * `listStudySessionQuestions`, not from anything the page remembered.
 */
export function remainingCards(
  questions: StudyQuestion[],
  attemptedIds: string[],
): StudyQuestion[] {
  const attempted = new Set(attemptedIds);
  return questions.filter((question) => !attempted.has(question.id));
}

/**
 * The session's anchor question: answered before studying as the pre-test and
 * again afterwards as the post-test, which is what makes the pre→post figure a
 * comparison rather than two unrelated numbers.
 */
export function anchorCard(
  questions: StudyQuestion[],
): StudyQuestion | undefined {
  return questions.at(0);
}

/** The practice deck: everything but the anchor, minus what is already answered. */
export function practiceCards(
  questions: StudyQuestion[],
  attemptedIds: string[],
): StudyQuestion[] {
  return remainingCards(questions.slice(1), attemptedIds);
}
