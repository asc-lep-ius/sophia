import type { components } from "$lib/api/schema";

/**
 * The session's selected learning path, as the numeric id every API route
 * takes, or `null` while none is selected.
 *
 * The tenant carries the id as a string. Anything that is not a positive
 * integer reads as "nothing selected" rather than being coerced, so no load
 * function can end up sending `NaN` to the API — which is how every real login
 * used to land on a dead end (#106).
 */
export function selectedLearningPathId(tenant: {
  learning_path_id: string | null;
}): number | null {
  const raw = tenant.learning_path_id;
  if (raw === null || !/^\d+$/.test(raw)) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export type LearningPath = components["schemas"]["LearningPathResponse"];

/** The listed learning paths, or `null` when the body is not the contract. */
export function readLearningPaths(body: unknown): LearningPath[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const paths = (body as { learning_paths?: unknown }).learning_paths;
  return Array.isArray(paths) && paths.every(isLearningPath) ? paths : null;
}

/**
 * The learning path a submitted picker names, or `null` for anything that is
 * not a positive integer — including no choice at all.
 */
export function readLearningPathChoice(form: FormData): number | null {
  const raw = form.get("learning_path_id");
  return typeof raw === "string"
    ? selectedLearningPathId({ learning_path_id: raw })
    : null;
}

function isLearningPath(value: unknown): value is LearningPath {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const path = value as Record<string, unknown>;
  return (
    typeof path.id === "number" &&
    typeof path.title === "string" &&
    typeof path.short_title === "string" &&
    (path.url === null || typeof path.url === "string")
  );
}
