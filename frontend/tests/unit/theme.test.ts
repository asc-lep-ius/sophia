import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  THEME_COOKIE,
  applyThemeToDocument,
  normalizeTheme,
  readThemeFromCookie,
  themeColorScheme,
  themeCookieValue,
} from "../../src/lib/theme";

describe("cookie-driven theme", () => {
  it("normalizes the three supported themes", () => {
    expect(normalizeTheme("light")).toBe("light");
    expect(normalizeTheme("dark")).toBe("dark");
    expect(normalizeTheme("oled")).toBe("oled");
    expect(normalizeTheme("sepia")).toBe("light");
  });

  it("builds an app-scoped theme cookie value", () => {
    expect(themeCookieValue("oled")).toContain(`${THEME_COOKIE}=oled`);
    expect(themeCookieValue("oled")).toContain("Path=/app");
  });

  it("reads the supported theme from a cookie header", () => {
    expect(readThemeFromCookie("session=abc; sophia-theme=dark; other=1")).toBe(
      "dark",
    );
    expect(readThemeFromCookie("sophia-theme=oled")).toBe("oled");
    expect(readThemeFromCookie("sophia-theme=sepia")).toBe("light");
    expect(readThemeFromCookie("")).toBe("light");
  });

  it("maps themes to the browser color-scheme", () => {
    expect(themeColorScheme("light")).toBe("light");
    expect(themeColorScheme("dark")).toBe("dark");
    expect(themeColorScheme("oled")).toBe("dark");
  });

  it("applies the selected theme to the document immediately", () => {
    applyThemeToDocument("oled", document);

    expect(document.documentElement.dataset.theme).toBe("oled");
    expect(document.documentElement.style.colorScheme).toBe("dark");

    applyThemeToDocument("light", document);

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("keeps the no-FOUC app.html script cookie-only", () => {
    const appHtml = readFileSync(join(process.cwd(), "src/app.html"), "utf8");
    expect(appHtml).toContain(THEME_COOKIE);
    expect(appHtml).toContain("oled");
    expect(appHtml).not.toContain("localStorage");
  });

  it("documents a local-only Inter and Atkinson font baseline", () => {
    const appCss = readFileSync(join(process.cwd(), "src/app.css"), "utf8");

    expect(appCss).toContain("Inter");
    expect(appCss).toContain("Atkinson Hyperlegible");
    expect(appCss).not.toMatch(/https?:|fonts\.googleapis|fonts\.gstatic/);
  });
});
