import {
  cookieName,
  defineCustomClientStrategy,
  defineCustomServerStrategy,
  toLocale,
} from "$lib/paraglide/runtime";

import { SOPHIA_LOCALE_COOKIE, normalizeLocale, type Locale } from "./locale";

/**
 * Where the `sophia-locale` compatibility alias sits in Paraglide's `strategy`,
 * which `vite.config.ts` restates and `locale.test.ts` holds to this name.
 */
export const LOCALE_ALIAS_STRATEGY = "custom-sophiaLocale";

/**
 * The locale the `sophia-locale` alias pins, unless Paraglide's own cookie
 * already pins one.
 *
 * The step-aside is load-bearing on the server: `extractLocaleFromRequestAsync`
 * runs every custom strategy before any built-in one, whatever the order in
 * `strategy`, so without it the alias would outrank `PARAGLIDE_LOCALE`. The
 * check is Paraglide's own `toLocale`, so the alias yields exactly when the
 * built-in cookie strategy is going to answer.
 */
export function aliasLocale(
  cookieHeader: string | null | undefined,
): Locale | undefined {
  const cookies = parseCookieHeader(cookieHeader);
  if (toLocale(cookies.get(cookieName))) {
    return undefined;
  }
  return normalizeLocale(cookies.get(SOPHIA_LOCALE_COOKIE));
}

export function defineServerLocaleAlias(): void {
  defineCustomServerStrategy(LOCALE_ALIAS_STRATEGY, {
    getLocale: (request) => aliasLocale(request?.headers.get("cookie")),
  });
}

/**
 * The client half keeps hydration in the language the server rendered: without
 * it the client runtime skips the alias, falls through to the browser's
 * preference and re-renders the page in that language instead.
 */
export function defineClientLocaleAlias(): void {
  defineCustomClientStrategy(LOCALE_ALIAS_STRATEGY, {
    getLocale: () => aliasLocale(document.cookie),
    // The alias is only ever read; saving pins `PARAGLIDE_LOCALE` instead.
    setLocale: () => undefined,
  });
}

/** First occurrence wins, as it does for Paraglide's own cookie lookup. */
function parseCookieHeader(
  header: string | null | undefined,
): Map<string, string> {
  const cookies = new Map<string, string>();
  for (const pair of header?.split(";") ?? []) {
    const separator = pair.indexOf("=");
    const name = pair.slice(0, separator).trim();
    if (separator > 0 && !cookies.has(name)) {
      cookies.set(name, pair.slice(separator + 1).trim());
    }
  }
  return cookies;
}
