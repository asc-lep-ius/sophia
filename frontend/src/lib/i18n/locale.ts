import type { Cookies } from "@sveltejs/kit";

export const LOCALE_COOKIE = "PARAGLIDE_LOCALE";
export const SOPHIA_LOCALE_COOKIE = "sophia-locale";
export const LOCALES = ["en", "de"] as const;

/**
 * Paraglide's generated `cookieMaxAge`, restated rather than imported so this
 * module stays free of the gitignored `$lib/paraglide` output. `locale.test.ts`
 * holds the two to each other.
 */
export const LOCALE_COOKIE_MAX_AGE = 34560000;

export type Locale = (typeof LOCALES)[number];

export function normalizeLocale(
  value: string | null | undefined,
): Locale | undefined {
  const lowered = value?.trim().toLowerCase();
  if (!lowered) {
    return undefined;
  }
  const primary = lowered.split("-")[0];
  return LOCALES.includes(primary as Locale) ? (primary as Locale) : undefined;
}

export function negotiateLocale(
  cookieLocale: string | null | undefined,
  acceptLanguage: string | null,
): Locale {
  const normalizedCookie = normalizeLocale(cookieLocale);
  if (normalizedCookie) {
    return normalizedCookie;
  }

  for (const item of acceptLanguage?.split(",") ?? []) {
    const [tag] = item.trim().split(";");
    const normalizedHeader = normalizeLocale(tag);
    if (normalizedHeader) {
      return normalizedHeader;
    }
  }

  return "en";
}

/**
 * Pin the UI locale the way Paraglide's own client runtime does.
 *
 * `path` and `maxAge` match the cookie `setLocale()` writes in the generated
 * `runtime.js`, so a server write and a later client write address one cookie
 * instead of two that shadow each other by path. `httpOnly` is off for the same
 * reason: the client runtime resolves the locale from `document.cookie`, and a
 * cookie it cannot read would leave the hydrated page in a different language
 * than the server rendered.
 *
 * `secure` follows the scheme rather than SvelteKit's default, which is `true`
 * for every host except `localhost` — the dev stack answers on
 * `http://127.0.0.1`, where that default leaves the cookie at the mercy of each
 * browser's trustworthy-origin rules.
 */
export function persistLocaleCookie(
  cookies: Cookies,
  locale: Locale,
  url: URL,
): void {
  cookies.set(LOCALE_COOKIE, locale, {
    httpOnly: false,
    maxAge: LOCALE_COOKIE_MAX_AGE,
    path: "/",
    sameSite: "lax",
    secure: url.protocol === "https:",
  });
}
