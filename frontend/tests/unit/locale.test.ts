import type { Cookies } from "@sveltejs/kit";
import { afterEach, describe, expect, it, vi } from "vitest";

import "../../src/hooks.client";
import {
  LOCALE_COOKIE,
  LOCALE_COOKIE_MAX_AGE,
  SOPHIA_LOCALE_COOKIE,
  negotiateLocale,
  normalizeLocale,
  persistLocaleCookie,
} from "../../src/lib/i18n/locale";
import {
  LOCALE_ALIAS_STRATEGY,
  aliasLocale,
} from "../../src/lib/i18n/locale-alias";
import {
  cookieMaxAge,
  cookieName,
  getLocaleForUrl,
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

describe("sophia-locale alias", () => {
  afterEach(() => {
    for (const name of [LOCALE_COOKIE, SOPHIA_LOCALE_COOKIE]) {
      document.cookie = `${name}=; path=/; max-age=0`;
    }
  });

  /**
   * The name is the compatibility promise in
   * docs/frontend-paraglide-decision.md item 4, so it is pinned literally: a
   * rename would leave every existing setup writing a cookie nothing reads.
   */
  it("keeps the documented name and sits between Paraglide's cookie and the browser", () => {
    expect(SOPHIA_LOCALE_COOKIE).toBe("sophia-locale");
    expect(strategy).toEqual([
      "cookie",
      LOCALE_ALIAS_STRATEGY,
      "preferredLanguage",
      "baseLocale",
    ]);
  });

  it("answers only when Paraglide's own cookie does not", () => {
    expect(aliasLocale(`${SOPHIA_LOCALE_COOKIE}=de`)).toBe("de");
    expect(aliasLocale(`theme=dark; ${SOPHIA_LOCALE_COOKIE}=DE-at`)).toBe("de");
    expect(
      aliasLocale(`${LOCALE_COOKIE}=en; ${SOPHIA_LOCALE_COOKIE}=de`),
    ).toBeUndefined();
    expect(aliasLocale(`${SOPHIA_LOCALE_COOKIE}=fr`)).toBeUndefined();
    expect(aliasLocale(null)).toBeUndefined();
  });

  it("still answers when Paraglide's cookie holds nothing it can use", () => {
    expect(aliasLocale(`${LOCALE_COOKIE}=fr; ${SOPHIA_LOCALE_COOKIE}=de`)).toBe(
      "de",
    );
  });

  it("resolves on the client the way the server rendered", () => {
    document.cookie = `${SOPHIA_LOCALE_COOKIE}=de; path=/`;
    expect(getLocaleForUrl("http://localhost/app/settings")).toBe("de");

    document.cookie = `${LOCALE_COOKIE}=en; path=/`;
    expect(getLocaleForUrl("http://localhost/app/settings")).toBe("en");
  });
});
