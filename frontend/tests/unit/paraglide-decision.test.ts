import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const root = process.cwd();
const repoRoot = join(root, "..");

function readFrontend(path: string): string {
  return readFileSync(join(root, path), "utf8");
}

function readRepo(path: string): string {
  return readFileSync(join(repoRoot, path), "utf8");
}

describe("Paraglide adapter decision", () => {
  it("documents generated Paraglide JS v2 middleware as the frontend baseline", () => {
    const decision = readRepo("docs/frontend-paraglide-decision.md");

    expect(decision).toContain("Use generated Paraglide JS v2 middleware");
    expect(decision).toContain("retired `@inlang/paraglide-sveltekit`");
    expect(decision).toContain("frontend/tests/unit/web-vitals.test.ts");
    expect(decision).toContain("frontend/tests/unit/smoke.test.ts");
  });

  it("keeps Vite on the Paraglide JS compiler plugin", () => {
    const viteConfig = readFrontend("vite.config.ts");

    expect(viteConfig).toContain(
      'import { paraglideVitePlugin } from "@inlang/paraglide-js"',
    );
    expect(viteConfig).toContain('outdir: "./src/lib/paraglide"');
    expect(viteConfig).toContain('"preferredLanguage"');
  });

  it("keeps SvelteKit wired to generated middleware instead of the retired adapter", () => {
    const hooks = readFrontend("src/hooks.server.ts");

    expect(hooks).toContain(
      'import { paraglideMiddleware } from "$lib/paraglide/server"',
    );
    expect(hooks).toContain("paraglideMiddleware(");
    expect(hooks).toContain("sequence(contextHandle, paraglideHandle)");
    expect(hooks).not.toContain("@inlang/paraglide-sveltekit");
  });

  it("keeps the retired adapter out of package and lock files", () => {
    const packageJson = readFrontend("package.json");
    const lockfile = readFrontend("pnpm-lock.yaml");

    expect(packageJson).toContain('"@inlang/paraglide-js": "2.18.1"');
    expect(packageJson).not.toContain("@inlang/paraglide-sveltekit");
    expect(lockfile).not.toContain("@inlang/paraglide-sveltekit");
  });
});
