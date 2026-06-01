import { readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const SCHEMA_URL = new URL("../src/lib/api/schema.d.ts", import.meta.url);
const HEADER_START_PATTERN = /^(\s*)headers: \{$/;
const UNKNOWN_HEADER_INDEX_PATTERN = /^\s*\[name: string\]: unknown;$/;
const VALIDATION_ERROR_START_PATTERN = /^(\s*)ValidationError: \{$/;
const VALIDATION_ERROR_INPUT_PATTERN = /^(\s*)input\?: unknown;$/;

/**
 * @typedef NormalizedOpenApiTypes
 * @property {string} content
 * @property {number} removedIndexes
 */

/**
 * @param {string} content
 * @returns {NormalizedOpenApiTypes}
 */
export function normalizeOpenApiTypesContent(content) {
  const lines = content.split("\n");
  /** @type {string[]} */
  const normalizedLines = [];
  let removedIndexes = 0;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    const match = HEADER_START_PATTERN.exec(line);
    if (!match) {
      normalizedLines.push(line);
      continue;
    }

    const headerIndent = match[1] ?? "";
    /** @type {string[]} */
    const bodyLines = [];
    let endIndex = index + 1;

    for (; endIndex < lines.length; endIndex += 1) {
      const bodyLine = lines[endIndex] ?? "";
      if (bodyLine === `${headerIndent}};`) {
        break;
      }
      if (UNKNOWN_HEADER_INDEX_PATTERN.test(bodyLine)) {
        removedIndexes += 1;
        continue;
      }
      bodyLines.push(bodyLine);
    }

    if (endIndex >= lines.length) {
      normalizedLines.push(line, ...bodyLines);
      break;
    }

    if (bodyLines.every((line) => line.trim() === "")) {
      normalizedLines.push(`${headerIndent}headers: Record<string, never>;`);
    } else {
      normalizedLines.push(line, ...bodyLines, lines[endIndex] ?? "");
    }

    index = endIndex;
    continue;
  }

  /** @type {string[]} */
  const validationNormalizedLines = [];

  for (let index = 0; index < normalizedLines.length; index += 1) {
    const line = normalizedLines[index] ?? "";
    const match = VALIDATION_ERROR_START_PATTERN.exec(line);
    if (!match) {
      validationNormalizedLines.push(line);
      continue;
    }

    const schemaIndent = match[1] ?? "";
    validationNormalizedLines.push(line);
    let endIndex = index + 1;

    for (; endIndex < normalizedLines.length; endIndex += 1) {
      const bodyLine = normalizedLines[endIndex] ?? "";
      const inputMatch = VALIDATION_ERROR_INPUT_PATTERN.exec(bodyLine);
      validationNormalizedLines.push(
        inputMatch ? `${inputMatch[1] ?? ""}input?: never;` : bodyLine,
      );

      if (bodyLine === `${schemaIndent}};`) {
        break;
      }
    }

    if (endIndex >= normalizedLines.length) {
      break;
    }

    index = endIndex;
  }

  return { content: validationNormalizedLines.join("\n"), removedIndexes };
}

/**
 * @param {string | URL} [schemaPath]
 * @returns {Promise<number>}
 */
export async function normalizeOpenApiTypes(schemaPath = SCHEMA_URL) {
  const content = await readFile(schemaPath, "utf8");
  const normalized = normalizeOpenApiTypesContent(content);
  if (normalized.content !== content) {
    await writeFile(schemaPath, normalized.content, "utf8");
  }
  return normalized.removedIndexes;
}

/** @returns {Promise<void>} */
async function main() {
  await normalizeOpenApiTypes();
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  await main();
}
