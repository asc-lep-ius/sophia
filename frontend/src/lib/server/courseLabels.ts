import { apiFetch } from "../../hooks.server";
import { readLearningPaths } from "$lib/learningPath";

/**
 * Short course titles by learning path id, for labelling each review.
 *
 * Only a label: a TUWEL outage leaves the map empty and the page falls back to
 * the id, rather than hiding reviews the database still holds.
 */
export async function loadCourseLabels(
  event: Parameters<typeof apiFetch>[0],
): Promise<Record<number, string>> {
  try {
    const response = await apiFetch(event, "/api/learning-paths");
    if (!response.ok) {
      return {};
    }
    const paths = readLearningPaths(await response.json()) ?? [];
    return Object.fromEntries(paths.map((path) => [path.id, path.short_title]));
  } catch {
    return {};
  }
}
