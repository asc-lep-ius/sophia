import type { Cookies } from "@sveltejs/kit";

export const THEME_COOKIE = "sophia-theme";
export const THEME_COOKIE_MAX_AGE = 31536000;
export const THEMES = ["light", "dark", "oled"] as const;

export type Theme = (typeof THEMES)[number];
export type ThemeColorScheme = "light" | "dark";

const THEME_COOKIE_PATTERN = /(?:^|; )sophia-theme=(light|dark|oled)(?:;|$)/;

export function normalizeTheme(value: string | null | undefined): Theme {
  return THEMES.includes(value as Theme) ? (value as Theme) : "light";
}

/**
 * Pin the theme the pre-hydration script in `app.html` paints from.
 *
 * Written only once the session record has taken the same value, so the cookie
 * never names a theme the next render's layout data would disagree with.
 * `httpOnly` is off because that script reads it from `document.cookie`.
 */
export function persistThemeCookie(
  cookies: Cookies,
  theme: Theme,
  url: URL,
): void {
  cookies.set(THEME_COOKIE, theme, {
    httpOnly: false,
    maxAge: THEME_COOKIE_MAX_AGE,
    path: "/app",
    sameSite: "lax",
    secure: url.protocol === "https:",
  });
}

export function readThemeFromCookie(
  cookieHeader: string | null | undefined,
): Theme {
  return normalizeTheme(cookieHeader?.match(THEME_COOKIE_PATTERN)?.[1]);
}

export function themeColorScheme(theme: Theme): ThemeColorScheme {
  return theme === "light" ? "light" : "dark";
}

export function applyThemeToDocument(
  theme: Theme,
  target: Document = document,
): void {
  target.documentElement.dataset.theme = theme;
  target.documentElement.style.colorScheme = themeColorScheme(theme);
}
