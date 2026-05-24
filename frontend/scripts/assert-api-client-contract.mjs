import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const API_ROOT_URL = new URL("../src/lib/api", import.meta.url);
const CLIENT_WRAPPER = "frontend/src/lib/api/client.ts";
const OPENAPI_METHOD_PATTERN =
  /\.\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*(<[^>()]+>)?\s*\(\s*([^,\n\r)]*)/g;
const OPENAPI_FETCH_PATTERN =
  /\bfrom\s+["']openapi-fetch["']|\bimport\s*\(\s*["']openapi-fetch["']\s*\)|\brequire\s*\(\s*["']openapi-fetch["']\s*\)/;
const SOURCE_EXTENSIONS = new Set([".js", ".mjs", ".svelte", ".ts"]);

/**
 * @typedef ApiClientFile
 * @property {string} path
 * @property {string} content
 */

/**
 * @typedef ManualCastRule
 * @property {RegExp} pattern
 * @property {string} message
 */

/** @type {ManualCastRule[]} */
const MANUAL_CASTS = [
  {
    pattern: /\bas\s+ApiPath\b/,
    message: "casts to ApiPath instead of using a generated literal path",
  },
  {
    pattern: /\bas\s+BodyInit\b/,
    message: "casts to BodyInit instead of generated request body types",
  },
  {
    pattern: /\bas\s+Response\b/,
    message: "casts to Response instead of generated response types",
  },
  {
    pattern: /\bas\s+ResponseInit\b/,
    message: "casts to ResponseInit instead of generated response types",
  },
  {
    pattern: /\bas\s+(?:components|operations|paths)(?:\b|\[)/,
    message: "casts to generated API types instead of using typed client calls",
  },
];

/**
 * @param {ApiClientFile[]} files
 * @returns {string[]}
 */
export function validateApiClientContract(files) {
  /** @type {string[]} */
  const errors = [];
  for (const file of files) {
    errors.push(...validateApiClientFile(file));
  }
  return errors;
}

/**
 * @param {string} [apiRoot]
 * @returns {Promise<ApiClientFile[]>}
 */
export async function readApiClientFiles(
  apiRoot = fileURLToPath(API_ROOT_URL),
) {
  /** @type {ApiClientFile[]} */
  const files = [];
  await collectApiClientFiles(apiRoot, files);
  return files;
}

/** @param {ApiClientFile[]} files */
export function assertApiClientContract(files) {
  const errors = validateApiClientContract(files);
  if (errors.length) {
    throw new Error(
      `API client contract violations for #91:\n- ${errors.join("\n- ")}`,
    );
  }
}

/**
 * @param {ApiClientFile} file
 * @returns {string[]}
 */
function validateApiClientFile(file) {
  /** @type {string[]} */
  const errors = [];
  const lines = file.content.split(/\r?\n/);

  lines.forEach((line, index) => {
    const lineNumber = index + 1;
    if (/\bas\s+any\b/.test(line)) {
      errors.push(`${file.path}:${lineNumber} uses forbidden \`as any\``);
    }

    if (OPENAPI_FETCH_PATTERN.test(line) && !isClientWrapper(file.path)) {
      errors.push(
        `${file.path}:${lineNumber} imports openapi-fetch outside ${CLIENT_WRAPPER}`,
      );
    }

    for (const cast of MANUAL_CASTS) {
      if (cast.pattern.test(line)) {
        errors.push(`${file.path}:${lineNumber} ${cast.message}`);
      }
    }
  });

  errors.push(...validateOpenApiMethodCalls(file));
  return errors;
}

/**
 * @param {ApiClientFile} file
 * @returns {string[]}
 */
function validateOpenApiMethodCalls(file) {
  /** @type {string[]} */
  const errors = [];
  for (const match of file.content.matchAll(OPENAPI_METHOD_PATTERN)) {
    const method = match[1] ?? "UNKNOWN";
    const generic = match[2] ?? "";
    const argument = match[3]?.trim() ?? "";
    const lineNumber = lineNumberAt(file.content, match.index ?? 0);

    if (generic) {
      errors.push(
        `${file.path}:${lineNumber} adds a manual OpenAPI method generic`,
      );
    }

    if (isDynamicPathArgument(argument)) {
      errors.push(
        `${file.path}:${lineNumber} builds an OpenAPI path dynamically`,
      );
      continue;
    }

    if (!isStringLiteralPathArgument(argument)) {
      errors.push(
        `${file.path}:${lineNumber} calls ${method} with a non-literal OpenAPI path`,
      );
    }
  }
  return errors;
}

/** @param {string} argument */
function isDynamicPathArgument(argument) {
  return argument.startsWith("`") || argument.includes("+");
}

/** @param {string} argument */
function isStringLiteralPathArgument(argument) {
  return /^(["'])\/api\/.*\1$/.test(argument);
}

/**
 * @param {string} content
 * @param {number} index
 */
function lineNumberAt(content, index) {
  return content.slice(0, index).split(/\r?\n/).length;
}

/** @param {string} filePath */
function isClientWrapper(filePath) {
  const normalized = normalizePath(filePath);
  return (
    normalized.endsWith("frontend/src/lib/api/client.ts") ||
    normalized.endsWith("src/lib/api/client.ts")
  );
}

/**
 * @param {string} directory
 * @param {ApiClientFile[]} files
 * @returns {Promise<void>}
 */
async function collectApiClientFiles(directory, files) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      await collectApiClientFiles(path, files);
      continue;
    }

    if (!isScannedSourceFile(entry.name)) {
      continue;
    }

    files.push({
      path: normalizePath(relative(process.cwd(), path)),
      content: await readFile(path, "utf8"),
    });
  }
}

/** @param {string} fileName */
function isScannedSourceFile(fileName) {
  if (fileName.endsWith(".d.ts")) {
    return false;
  }
  const extensionIndex = fileName.lastIndexOf(".");
  if (extensionIndex === -1) {
    return false;
  }
  return SOURCE_EXTENSIONS.has(fileName.slice(extensionIndex));
}

/** @param {string} filePath */
function normalizePath(filePath) {
  return filePath.replaceAll("\\", "/");
}

/** @returns {Promise<void>} */
async function main() {
  assertApiClientContract(await readApiClientFiles());
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  await main();
}
