import { normalizeTheme, THEME_COOKIE } from "$lib/theme";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = ({ cookies, locals }) => ({
  locale: locals.locale,
  tenant: locals.tenant,
  theme: normalizeTheme(cookies.get(THEME_COOKIE)),
});
