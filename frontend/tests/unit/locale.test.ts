import { describe, expect, it } from "vitest";

import { negotiateLocale, normalizeLocale } from "../../src/lib/i18n/locale";

describe("locale negotiation", () => {
  it("normalizes supported locale tags", () => {
    expect(normalizeLocale("de-AT")).toBe("de");
    expect(normalizeLocale("EN-us")).toBe("en");
    expect(normalizeLocale("fr")).toBeUndefined();
  });

  it("prefers the locale cookie over Accept-Language", () => {
    expect(negotiateLocale("de", "en-US,en;q=0.9")).toBe("de");
  });

  it("uses browser preference and falls back to English", () => {
    expect(negotiateLocale(undefined, "fr-CH, de;q=0.8")).toBe("de");
    expect(negotiateLocale(undefined, "fr-CH")).toBe("en");
  });
});
