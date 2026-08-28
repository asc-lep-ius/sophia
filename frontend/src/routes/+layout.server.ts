import { normalizeTheme, THEME_COOKIE, THEMES, type Theme } from "$lib/theme";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = ({ cookies, locals }) => {
  const sessionTheme = themeFromSessionSettings(locals.sessionSettings?.theme);

  return {
    authenticated: locals.authenticated,
    locale: locals.locale,
    settings: locals.sessionSettings,
    tenant: locals.tenant,
    theme: sessionTheme ?? normalizeTheme(cookies.get(THEME_COOKIE)),
    user: locals.user,
  };
};

function themeFromSessionSettings(
  theme: string | null | undefined,
): Theme | undefined {
  return THEMES.includes(theme as Theme) ? (theme as Theme) : undefined;
}
