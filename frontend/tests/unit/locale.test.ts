import type { Cookies } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import {
  LOCALE_COOKIE,
  LOCALE_COOKIE_MAX_AGE,
  negotiateLocale,
  normalizeLocale,
  persistLocaleCookie,
} from "../../src/lib/i18n/locale";
import {
  cookieMaxAge,
  cookieName,
  strategy,
} from "../../src/lib/paraglide/runtime";

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

describe("locale cookie", () => {
  /**
   * The names here are restated rather than imported into `locale.ts`, which
   * keeps that module free of the gitignored Paraglide output. This is what
   * stops the two drifting apart silently — a server write under a different
   * name or path would be a cookie nothing reads.
   */
  it("agrees with the cookie Paraglide's own runtime reads and writes", () => {
    expect(LOCALE_COOKIE).toBe(cookieName);
    expect(LOCALE_COOKIE_MAX_AGE).toBe(cookieMaxAge);
    expect(strategy[0]).toBe("cookie");
  });

  it("writes at Paraglide's own path and stays readable to the client runtime", () => {
    const set = vi.fn();

    persistLocaleCookie(
      { set } as unknown as Cookies,
      "de",
      new URL("http://127.0.0.1:5173/app/settings"),
    );

    expect(set).toHaveBeenCalledWith(LOCALE_COOKIE, "de", {
      httpOnly: false,
      maxAge: LOCALE_COOKIE_MAX_AGE,
      path: "/",
      sameSite: "lax",
      secure: false,
    });
  });

  it("marks the cookie secure behind HTTPS", () => {
    const set = vi.fn();

    persistLocaleCookie(
      { set } as unknown as Cookies,
      "en",
      new URL("https://sophia.example/app/settings"),
    );

    expect(set).toHaveBeenCalledWith(
      LOCALE_COOKIE,
      "en",
      expect.objectContaining({ secure: true }),
    );
  });
});
