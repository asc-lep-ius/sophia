import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  THEME_COOKIE,
  normalizeTheme,
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

  it("keeps the no-FOUC app.html script cookie-only", () => {
    const appHtml = readFileSync(join(process.cwd(), "src/app.html"), "utf8");
    expect(appHtml).toContain(THEME_COOKIE);
    expect(appHtml).toContain("oled");
    expect(appHtml).not.toContain("localStorage");
  });
});
