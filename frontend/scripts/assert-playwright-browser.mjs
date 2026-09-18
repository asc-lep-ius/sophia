// The browser is baked into the CI image (ci/Dockerfile.frontend), not installed
// per run, so a lockfile bump that outruns a rebuild of that image leaves the
// jobs pointing at browser builds their Playwright does not know about.
// Playwright reports that itself, but only after each of the three browser jobs
// has built and started a preview server, and its advice -- run
// `playwright install` -- is the per-run install this image exists to remove.
// This says it once, up front, and names the job that fixes it.
//
// Every location Playwright would install to is checked, not just the headed
// browser. A headless run launches chromium_headless_shell rather than chromium,
// and playwright-core's browsers.json revisions the two independently, so a
// release that moved only the shell would walk straight past a check that looked
// at chromium alone.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

const INSTALL_LOCATION = /^\s*Install location:\s+(\S.*?)\s*$/;

/**
 * `playwright install --dry-run` prints one stanza per browser it would
 * install. ffmpeg appears under more than one of them, so locations are
 * deduplicated rather than counted.
 * @param {string} dryRunOutput
 * @returns {string[]}
 */
export function parseInstallLocations(dryRunOutput) {
  /** @type {Set<string>} */
  const locations = new Set();
  for (const line of dryRunOutput.split("\n")) {
    const location = INSTALL_LOCATION.exec(line)?.[1];
    if (location) {
      locations.add(location);
    }
  }
  return [...locations];
}

/**
 * @param {string[]} locations
 * @param {(path: string) => boolean} [exists]
 * @returns {string[]}
 */
export function findMissingBrowserPaths(locations, exists = existsSync) {
  return locations.filter((location) => !exists(location));
}

/**
 * @param {string[]} locations
 * @param {(path: string) => boolean} [exists]
 * @returns {string[]}
 */
export function validatePlaywrightBrowsers(locations, exists = existsSync) {
  // No stanza at all is a parse failure, not a clean bill of health. Failing
  // closed matters more here than anywhere else in this file: the whole point
  // is to catch an image nobody verified, and a guard that reads an output it
  // no longer understands as "nothing missing" is the silence it exists to end.
  if (!locations.length) {
    return [
      "`playwright install --dry-run chromium` reported no install location — its output format has changed and this guard needs updating",
    ];
  }
  return findMissingBrowserPaths(locations, exists).map(
    (location) => `missing browser build: ${location}`,
  );
}

/**
 * @param {string[]} locations
 * @param {(path: string) => boolean} [exists]
 * @returns {void}
 */
export function assertPlaywrightBrowsers(locations, exists = existsSync) {
  const errors = validatePlaywrightBrowsers(locations, exists);
  if (errors.length) {
    throw new Error(
      `Playwright cannot run against the browsers installed here:\n- ${errors.join("\n- ")}\n` +
        "In CI: the frontend-ci image predates frontend/pnpm-lock.yaml — run the " +
        "rebuild-frontend-ci-image job, then retry this one.\n" +
        "Locally: pnpm -C frontend exec playwright install chromium",
    );
  }
}

// Resolved here rather than at module scope, and not from PATH. At module scope
// it breaks the unit test -- vitest serves modules over http://, so import.meta.url
// is not a file URL until something actually asks for the binary. From PATH it
// would work under `pnpm run` and nowhere else.
/** @returns {string[]} */
export function readInstallLocations() {
  const cli = fileURLToPath(
    new URL("../node_modules/.bin/playwright", import.meta.url),
  );
  return parseInstallLocations(
    execFileSync(cli, ["install", "--dry-run", "chromium"], {
      encoding: "utf8",
    }),
  );
}

/** @returns {void} */
function main() {
  assertPlaywrightBrowsers(readInstallLocations());
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main();
}
