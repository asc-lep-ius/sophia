import type { StudyPacing, StudyQuestion } from "$lib/api/study";

export type EnforcedPolicy = {
  minElaborationChars: number;
  minPromptDwellMs: number;
};

/**
 * The floors the server will actually check for this question.
 *
 * The question carries the policy it was issued with, which is the one the
 * attempt endpoint evaluates; the deployment-wide pacing values are the
 * fallback for a format that carries none. Reading them off the question means
 * the surface cannot disagree with the server about what is required.
 */
export function enforcedPolicy(
  question: StudyQuestion,
  pacing: StudyPacing,
): EnforcedPolicy {
  if (question.engagement_policy.kind === "elaboration") {
    return {
      minElaborationChars: question.engagement_policy.min_elaboration_chars,
      minPromptDwellMs: question.engagement_policy.min_prompt_dwell_ms,
    };
  }
  return {
    minElaborationChars: pacing.elaboration_min_chars,
    minPromptDwellMs: pacing.prompt_min_dwell_ms,
  };
}
