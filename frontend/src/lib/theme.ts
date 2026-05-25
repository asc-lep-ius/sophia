export const THEME_COOKIE = "sophia-theme";
export const THEMES = ["light", "dark", "oled"] as const;

export type Theme = (typeof THEMES)[number];
export type ThemeColorScheme = "light" | "dark";

const THEME_COOKIE_PATTERN = /(?:^|; )sophia-theme=(light|dark|oled)(?:;|$)/;

export function normalizeTheme(value: string | null | undefined): Theme {
  return THEMES.includes(value as Theme) ? (value as Theme) : "light";
}

export function themeCookieValue(theme: Theme): string {
  return `${THEME_COOKIE}=${theme}; Path=/app; SameSite=Lax; Max-Age=31536000`;
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

export function persistTheme(theme: Theme, target: Document = document): void {
  target.cookie = themeCookieValue(theme);
  applyThemeToDocument(theme, target);
}
