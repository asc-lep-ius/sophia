import { describe, expect, it } from "vitest";

import {
  assertPlaywrightBrowsers,
  findMissingBrowserPaths,
  parseInstallLocations,
  validatePlaywrightBrowsers,
} from "../../scripts/assert-playwright-browser.mjs";

const HEADED = "/ms-playwright/chromium-1223";
const FFMPEG = "/ms-playwright/ffmpeg-1011";
const HEADLESS_SHELL = "/ms-playwright/chromium_headless_shell-1223";

// Trimmed from the real output of `playwright install --dry-run chromium` under
// Playwright 1.60, including the duplicated ffmpeg stanza.
const DRY_RUN_OUTPUT = [
  "Chrome for Testing 148.0.7778.96 (playwright chromium v1223)",
  `  Install location:    ${HEADED}`,
  "  Download url:        https://cdn.playwright.dev/builds/cft/148.0.7778.96/linux64/chrome-linux64.zip",
  "",
  "FFmpeg (playwright ffmpeg v1011)",
  `  Install location:    ${FFMPEG}`,
  "  Download url:        https://cdn.playwright.dev/builds/ffmpeg/1011/ffmpeg-linux.zip",
  "",
  "Chrome Headless Shell 148.0.7778.96 (playwright chromium-headless-shell v1223)",
  `  Install location:    ${HEADLESS_SHELL}`,
  "  Download url:        https://cdn.playwright.dev/builds/cft/148.0.7778.96/linux64/chrome-headless-shell-linux64.zip",
  "",
  "FFmpeg (playwright ffmpeg v1011)",
  `  Install location:    ${FFMPEG}`,
  "",
].join("\n");

describe("playwright browser guard", () => {
  it("reads every install location once, the headless shell included", () => {
    expect(parseInstallLocations(DRY_RUN_OUTPUT)).toEqual([
      HEADED,
      FFMPEG,
      HEADLESS_SHELL,
    ]);
  });

  it("passes an image that carries all of them", () => {
    const locations = parseInstallLocations(DRY_RUN_OUTPUT);
    expect(validatePlaywrightBrowsers(locations, () => true)).toEqual([]);
    expect(() => assertPlaywrightBrowsers(locations, () => true)).not.toThrow();
  });

  // The regression test for the gap this guard shipped with: it checked the
  // headed chromium alone, and all three CI jobs run headless.
  it("rejects an image whose headless shell is missing", () => {
    const locations = parseInstallLocations(DRY_RUN_OUTPUT);
    const exists = (path: string) => path !== HEADLESS_SHELL;

    expect(findMissingBrowserPaths(locations, exists)).toEqual([
      HEADLESS_SHELL,
    ]);
    expect(() => assertPlaywrightBrowsers(locations, exists)).toThrow(
      /chromium_headless_shell-1223/,
    );
  });

  it("names the job that rebuilds the image", () => {
    expect(() => assertPlaywrightBrowsers([HEADED], () => false)).toThrow(
      /rebuild-frontend-ci-image/,
    );
  });

  // An unparseable dry run is not a clean bill of health.
  it("refuses output it could not parse", () => {
    expect(parseInstallLocations("Downloading something else\n")).toEqual([]);
    expect(validatePlaywrightBrowsers([], () => true)).toHaveLength(1);
    expect(() => assertPlaywrightBrowsers([], () => true)).toThrow(
      /output format has changed/,
    );
  });
});
