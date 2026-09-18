// The browser is baked into the CI image (ci/Dockerfile.frontend), not installed
// per run, so a lockfile bump that outruns a rebuild of that image leaves the
// jobs pointing at a Chromium revision their Playwright does not know about.
// Playwright would report that itself, but only after each of the three browser
// jobs has built and started the preview server, and it reads as a test failure
// rather than as a stale image. This says it once, up front, by name.
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { chromium } from "@playwright/test";

const { version } = createRequire(import.meta.url)(
  "@playwright/test/package.json",
);
const executable = chromium.executablePath();

if (!existsSync(executable)) {
  throw new Error(
    `Playwright ${version} expects a Chromium build at ${executable}, and nothing is there.\n` +
      `In CI: the frontend-ci image predates frontend/pnpm-lock.yaml — run the ` +
      `rebuild-frontend-ci-image job, then retry this one.\n` +
      `Locally: pnpm -C frontend exec playwright install chromium`,
  );
}
