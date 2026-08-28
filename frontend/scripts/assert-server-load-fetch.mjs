import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const RAW_FETCH_CALL_PATTERN = /(?:^|[^\w$])fetch\s*\(/;

/**
 * @typedef ServerLoadFile
 * @property {string} path
 * @property {string} content
 */

/**
 * @param {ServerLoadFile[]} files
 * @returns {string[]}
 */
export function validateServerLoadFetchContract(files) {
  return files
    .filter((file) => hasRawFetchCall(file.content))
    .map((file) => file.path);
}

/**
 * @param {string} [routesDir]
 * @returns {Promise<string[]>}
 */
export async function findServerLoadFetchOffenders(
  routesDir = getDefaultRoutesDir(),
) {
  return validateServerLoadFetchContract(await readServerLoadFiles(routesDir));
}

/**
 * @param {string} [routesDir]
 * @returns {Promise<ServerLoadFile[]>}
 */
export async function readServerLoadFiles(routesDir = getDefaultRoutesDir()) {
  /** @type {ServerLoadFile[]} */
  const files = [];
  await collectServerLoadFiles(routesDir, files);
  return files;
}

/** @param {ServerLoadFile[]} files */
export function assertServerLoadFetchContract(files) {
  const offenders = validateServerLoadFetchContract(files);
  if (offenders.length) {
    throw new Error(
      `Server loads must use apiFetch(event, path, init): ${offenders.join(", ")}`,
    );
  }
}

/** @param {string} content */
function hasRawFetchCall(content) {
  return RAW_FETCH_CALL_PATTERN.test(content);
}

function getDefaultRoutesDir() {
  if (import.meta.url.startsWith("file:")) {
    return fileURLToPath(new URL("../src/routes", import.meta.url));
  }
  return join(process.cwd(), "src/routes");
}

/**
 * @param {string} dir
 * @param {ServerLoadFile[]} files
 * @returns {Promise<void>}
 */
async function collectServerLoadFiles(dir, files) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      await collectServerLoadFiles(path, files);
      continue;
    }

    if (!entry.name.endsWith(".server.ts")) {
      continue;
    }

    files.push({ path, content: await readFile(path, "utf8") });
  }
}

/** @returns {Promise<void>} */
async function main() {
  assertServerLoadFetchContract(await readServerLoadFiles());
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  await main();
}
