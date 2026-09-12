import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

/** The wizard has no landing page of its own; step one is the landing page. */
export const load: PageServerLoad = () => {
  redirect(307, "/app/quickstart/welcome");
};
