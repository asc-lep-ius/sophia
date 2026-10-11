/** A 0–1 score as the whole percentage the study surface shows, or a dash. */
export function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${Math.round(value * 100)}%`;
}
