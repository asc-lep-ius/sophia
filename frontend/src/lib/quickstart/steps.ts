export type QuickstartStep = "welcome" | "topics" | "predict" | "done";

export const QUICKSTART_STEPS: QuickstartStep[] = [
  "welcome",
  "topics",
  "predict",
  "done",
];

/**
 * Which step a pathname is on.
 *
 * The URL is the wizard's only state. Nothing about a learner's progress lives
 * in a module-level store: one of those is shared across every SSR request in
 * the process, so a wizard built on it hands one learner's half-finished
 * onboarding to the next. It also survives a reload, a back button and a
 * shared link, which a store does not.
 */
export function stepFromPath(pathname: string): QuickstartStep {
  const trimmed = pathname.replace(/\/+$/, "");
  const last = trimmed.slice(trimmed.lastIndexOf("/") + 1);
  return QUICKSTART_STEPS.find((step) => step === last) ?? "welcome";
}

export function stepNumber(step: QuickstartStep): number {
  return QUICKSTART_STEPS.indexOf(step) + 1;
}
