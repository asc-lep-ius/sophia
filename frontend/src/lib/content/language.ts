import type { components } from "$lib/api/schema";

export type ContentLanguage = components["schemas"]["ContentLanguage"];
export type ContentLanguageOrigin =
  components["schemas"]["ContentLanguageOrigin"];

export const LANGUAGE_PARAM = "lang";

/**
 * What language the *content* is in, and what decided that.
 *
 * Kept apart from the UI locale on purpose. A learner reading German course
 * material through an English interface is the normal case at TU Wien, and a
 * surface that folds the two together shows one of them wrongly. `origin` is
 * carried so the page can say which rung answered — the learner's `?lang=`
 * override, the learning path's own language, or the deployment default.
 */
export type ContentLanguageState = {
  language: ContentLanguage;
  origin: ContentLanguageOrigin;
  override: ContentLanguage | null;
};

const CONTENT_LANGUAGES: readonly ContentLanguage[] = ["de", "en"];

/**
 * The deployment default, used only when the API could not be reached.
 *
 * Matches `SOPHIA_DEFAULT_CONTENT_LANGUAGE`. Falling back to the UI locale
 * instead is exactly the misuse this phase guards against: it would quietly
 * translate a German exam into an English study surface.
 */
export const FALLBACK_CONTENT_LANGUAGE: ContentLanguage = "de";

export function normalizeContentLanguage(
  value: string | null | undefined,
): ContentLanguage | null {
  const lowered = value?.trim().toLowerCase() ?? "";
  return CONTENT_LANGUAGES.includes(lowered as ContentLanguage)
    ? (lowered as ContentLanguage)
    : null;
}

/** The `?lang=` a learner asked for, or `null` when they asked for nothing. */
export function readLanguageOverride(url: URL): ContentLanguage | null {
  return normalizeContentLanguage(url.searchParams.get(LANGUAGE_PARAM));
}

export function readContentLanguage(
  body: unknown,
  override: ContentLanguage | null,
): ContentLanguageState | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const record = body as Record<string, unknown>;
  const language = normalizeContentLanguage(
    typeof record.content_language === "string"
      ? record.content_language
      : null,
  );
  const origin = record.resolved_from;
  if (
    language === null ||
    (origin !== "override" &&
      origin !== "learning_path" &&
      origin !== "default")
  ) {
    return null;
  }
  return { language, origin, override };
}

export function fallbackContentLanguage(
  override: ContentLanguage | null,
): ContentLanguageState {
  return {
    language: override ?? FALLBACK_CONTENT_LANGUAGE,
    origin: override === null ? "default" : "override",
    override,
  };
}

/**
 * Carry an explicit `?lang=` onto the next page, as a form field.
 *
 * Without this, one hop between the content surfaces silently drops back to
 * the learning path's own language and the learner has to re-choose on every
 * page. Only an explicit override travels: when nothing was chosen, the next
 * page is free to resolve the language for itself.
 */
export function languageParams(
  override: ContentLanguage | null,
): Record<string, string> {
  return override === null ? {} : { [LANGUAGE_PARAM]: override };
}
