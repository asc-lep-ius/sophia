import { m } from "$lib/paraglide/messages.js";

/** A course's short title, or its id when the titles could not be read. */
export function courseLabel(
  courses: Record<number, string>,
  learningPathId: number,
): string {
  return (
    courses[learningPathId] ??
    m.review_course_fallback({ id: String(learningPathId) })
  );
}
