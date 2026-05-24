export const THEME_COOKIE = "sophia-theme";
export const THEMES = ["light", "dark", "oled"] as const;

export type Theme = (typeof THEMES)[number];

export function normalizeTheme(value: string | null | undefined): Theme {
  return THEMES.includes(value as Theme) ? (value as Theme) : "light";
}

export function themeCookieValue(theme: Theme): string {
  return `${THEME_COOKIE}=${theme}; Path=/app; SameSite=Lax; Max-Age=31536000`;
}
