import { fail, redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { selectedLearningPathId } from "$lib/learningPath";
import { generateSessionDeck } from "$lib/server/studyDeck";
import { preTestAnswered } from "$lib/study/deck";
import type { Actions, PageServerLoad } from "./$types";

/**
 * Send a learner who has not done the predict step back to it.
 *
 * "Resume" and the dashboard link straight here, and so does a typed URL. The
 * server takes the session's one prediction as the licence to answer any of
 * its cards, and refuses every grade with 412 when there is none — so a
 * session left on the predict route before the pre-test would otherwise open
 * on cards that can never be saved. The pre-test stands in for the prediction:
 * the predict route lets neither through without the other.
 */
export const load: PageServerLoad = async ({ parent }) => {
  const { attemptedQuestionIds, questions, sessionId } = await parent();
  if (!preTestAnswered(questions, attemptedQuestionIds)) {
    redirect(
      303,
      resolve("/study/[sessionId]/predict", { sessionId: String(sessionId) }),
    );
  }
};

export const actions: Actions = {
  /**
   * Generate another batch of cards for a session whose queue ran dry.
   *
   * A form action rather than a browser call: generation is a model round-trip
   * with no learner-process trace behind it, and the reload it causes is what
   * re-reads the extended question set through the layout load.
   */
  extend: async (event) => {
    const sessionId = Number(event.params.sessionId);
    const learningPathId = selectedLearningPathId(event.locals.tenant);
    const form = await event.request.formData();
    const topic = String(form.get("topic") ?? "").trim();

    if (!Number.isInteger(sessionId) || learningPathId === null || !topic) {
      return fail(400, { error: "study.extend_failed" });
    }

    const generated = await generateSessionDeck(event, {
      learningPathId,
      sessionId,
      topic,
    });
    if (!generated) {
      return fail(502, { error: "study.extend_failed" });
    }

    return { extended: true };
  },
};
