import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

/**
 * @typedef {"dependencies" | "devDependencies" | "optionalDependencies" | "peerDependencies"} DependencyBucket
 * @typedef {Partial<Record<DependencyBucket, Record<string, string>>> & {
 *   engines?: { node?: string };
 *   scripts?: Record<string, string>;
 * }} PackageJson
 */

const PACKAGE_JSON_URL = new URL("../package.json", import.meta.url);
const LOCKFILE_URL = new URL("../pnpm-lock.yaml", import.meta.url);

export const REQUIRED_NODE_ENGINE = ">=22.12.0";
export const GUARD_SCRIPT = "node ./scripts/assert-package-contract.mjs";

/** @type {Readonly<Record<string, string>>} */
export const REQUIRED_DEPENDENCIES = Object.freeze({
  "@inlang/paraglide-js": "2.18.1",
  "@tailwindcss/vite": "4.3.0",
  "mode-watcher": "1.1.0",
  "openapi-fetch": "0.17.0",
  svelte: "5.55.9",
  tailwindcss: "4.3.0",
  "web-vitals": "5.2.0",
});

/** @type {Readonly<Record<string, string>>} */
export const REQUIRED_DEV_DEPENDENCIES = Object.freeze({
  "@sveltejs/adapter-node": "5.5.4",
  "@sveltejs/kit": "2.61.0",
  "shadcn-svelte": "1.2.7",
  vite: "8.0.14",
  vitest: "4.1.7",
});

const FORBIDDEN_PACKAGES = ["@inlang/paraglide-sveltekit"];
/** @type {DependencyBucket[]} */
const PACKAGE_BUCKETS = [
  "dependencies",
  "devDependencies",
  "optionalDependencies",
  "peerDependencies",
];

/**
 * @param {PackageJson} packageJson
 * @param {DependencyBucket} bucket
 * @param {string} packageName
 * @returns {string | undefined}
 */
function dependencyVersion(packageJson, bucket, packageName) {
  const dependencies = packageJson[bucket];
  if (!dependencies || typeof dependencies !== "object") {
    return undefined;
  }

  const version = dependencies[packageName];
  return typeof version === "string" ? version : undefined;
}

/**
 * @param {string[]} errors
 * @param {PackageJson} packageJson
 * @param {DependencyBucket} bucket
 * @param {Readonly<Record<string, string>>} requiredPackages
 */
function assertPinnedPackages(errors, packageJson, bucket, requiredPackages) {
  for (const [packageName, expectedVersion] of Object.entries(
    requiredPackages,
  )) {
    const actualVersion = dependencyVersion(packageJson, bucket, packageName);
    if (actualVersion !== expectedVersion) {
      errors.push(
        `${bucket}.${packageName} must be pinned to ${expectedVersion} (found ${actualVersion ?? "missing"})`,
      );
    }
  }
}

/**
 * @param {PackageJson} packageJson
 * @param {string} lockfileContent
 * @returns {string[]}
 */
export function validatePackageContract(packageJson, lockfileContent) {
  /** @type {string[]} */
  const errors = [];

  assertPinnedPackages(
    errors,
    packageJson,
    "dependencies",
    REQUIRED_DEPENDENCIES,
  );
  assertPinnedPackages(
    errors,
    packageJson,
    "devDependencies",
    REQUIRED_DEV_DEPENDENCIES,
  );

  const nodeEngine = packageJson.engines?.node;
  if (nodeEngine !== REQUIRED_NODE_ENGINE) {
    errors.push(
      `engines.node must be ${REQUIRED_NODE_ENGINE} (found ${nodeEngine ?? "missing"})`,
    );
  }

  if (packageJson.scripts?.["guard:package-contract"] !== GUARD_SCRIPT) {
    errors.push(`scripts.guard:package-contract must be "${GUARD_SCRIPT}"`);
  }

  for (const packageName of FORBIDDEN_PACKAGES) {
    for (const bucket of PACKAGE_BUCKETS) {
      if (dependencyVersion(packageJson, bucket, packageName)) {
        errors.push(`${packageName} must not appear in ${bucket}`);
      }
    }

    if (lockfileContent.includes(packageName)) {
      errors.push(`pnpm-lock.yaml must not contain ${packageName}`);
    }
  }

  return errors;
}

/**
 * @param {PackageJson} packageJson
 * @param {string} lockfileContent
 */
export function assertPackageContract(packageJson, lockfileContent) {
  const errors = validatePackageContract(packageJson, lockfileContent);
  if (errors.length) {
    throw new Error(
      `Package contract drift for #91:\n- ${errors.join("\n- ")}`,
    );
  }
}

async function main() {
  const [packageJsonContent, lockfileContent] = await Promise.all([
    readFile(PACKAGE_JSON_URL, "utf8"),
    readFile(LOCKFILE_URL, "utf8"),
  ]);

  assertPackageContract(
    /** @type {PackageJson} */ (JSON.parse(packageJsonContent)),
    lockfileContent,
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  await main();
}
