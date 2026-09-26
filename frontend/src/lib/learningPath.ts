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
