import { describe, expect, it } from "vitest";

import {
  REQUIRED_DEPENDENCIES,
  REQUIRED_DEV_DEPENDENCIES,
  REQUIRED_NODE_ENGINE,
  validatePackageContract,
} from "../../scripts/assert-package-contract.mjs";

type PackageJsonFixture = {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
  engines?: { node?: string };
  scripts: Record<string, string>;
};

const validPackageJson = (): PackageJsonFixture => ({
  dependencies: { ...REQUIRED_DEPENDENCIES },
  devDependencies: { ...REQUIRED_DEV_DEPENDENCIES },
  engines: { node: REQUIRED_NODE_ENGINE },
  scripts: {
    "guard:package-contract": "node ./scripts/assert-package-contract.mjs",
  },
});

describe("package contract", () => {
  it("accepts the exact frontend package baseline", () => {
    expect(
      validatePackageContract(validPackageJson(), "lockfileVersion: '9.0'\n"),
    ).toEqual([]);
  });

  it("rejects the retired Paraglide SvelteKit adapter package", () => {
    const packageJson = validPackageJson();
    packageJson.dependencies["@inlang/paraglide-sveltekit"] = "0.16.1";

    expect(validatePackageContract(packageJson, "")).toContain(
      "@inlang/paraglide-sveltekit must not appear in dependencies",
    );
    expect(
      validatePackageContract(
        validPackageJson(),
        "packages:\n  '@inlang/paraglide-sveltekit@0.16.1': {}\n",
      ),
    ).toContain("pnpm-lock.yaml must not contain @inlang/paraglide-sveltekit");
  });

  it("rejects missing engines, drifted pins, and missing guard script", () => {
    const packageJson = validPackageJson();
    packageJson.engines = undefined;
    packageJson.scripts = {};
    packageJson.dependencies = Object.fromEntries(
      Object.entries(packageJson.dependencies).filter(
        ([packageName]) => packageName !== "mode-watcher",
      ),
    );
    packageJson.devDependencies["@sveltejs/kit"] = "2.61.1";

    expect(validatePackageContract(packageJson, "")).toEqual(
      expect.arrayContaining([
        "dependencies.mode-watcher must be pinned to 1.1.0 (found missing)",
        "devDependencies.@sveltejs/kit must be pinned to 2.61.0 (found 2.61.1)",
        "engines.node must be >=22.12.0 (found missing)",
        'scripts.guard:package-contract must be "node ./scripts/assert-package-contract.mjs"',
      ]),
    );
  });
});
