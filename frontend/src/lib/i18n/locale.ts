export const LOCALE_COOKIE = "PARAGLIDE_LOCALE";
export const SOPHIA_LOCALE_COOKIE = "sophia-locale";
export const LOCALES = ["en", "de"] as const;

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
