import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const SCHEMA_URL = new URL("../src/lib/api/schema.d.ts", import.meta.url);
const FORBIDDEN_TYPE_PATTERN = /\b(?:any|unknown)\b/g;
const STRING_DELIMITERS = new Set(["'", '"', "`"]);

/**
 * @param {string} content
 * @param {string} [sourcePath]
 * @returns {string[]}
 */
export function validateOpenApiTypes(content, sourcePath = "schema.d.ts") {
  const scannerState = { blockComment: false, stringDelimiter: null };

  return content.split(/\r?\n/).flatMap((line, index) => {
    const typeLine = stripTypeScriptTrivia(line, scannerState);
    return forbiddenTypeTokens(typeLine).map(
      (typeToken) =>
        `${sourcePath}:${index + 1} contains forbidden generated OpenAPI type \`${typeToken}\``,
    );
  });
}

/**
 * @param {string} line
 * @param {{ blockComment: boolean, stringDelimiter: string | null }} state
 * @returns {string}
 */
function stripTypeScriptTrivia(line, state) {
  let typeLine = "";
  let escaped = false;
  let index = 0;

  while (index < line.length) {
    const character = line[index] ?? "";
    const nextCharacter = line[index + 1] ?? "";

    if (state.blockComment) {
      if (character === "*" && nextCharacter === "/") {
        state.blockComment = false;
        index += 2;
      } else {
        index += 1;
      }
      continue;
    }

    if (state.stringDelimiter !== null) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === state.stringDelimiter) {
        state.stringDelimiter = null;
      }
      index += 1;
      continue;
    }

    if (character === "/" && nextCharacter === "/") {
      break;
    }
    if (character === "/" && nextCharacter === "*") {
      state.blockComment = true;
      index += 2;
      continue;
    }
    if (STRING_DELIMITERS.has(character)) {
      state.stringDelimiter = character;
      index += 1;
      continue;
    }

    typeLine += character;
    index += 1;
  }

  return typeLine;
}

/**
 * @param {string} line
 * @returns {string[]}
 */
function forbiddenTypeTokens(line) {
  /** @type {string[]} */
  const tokens = [];

  for (const match of line.matchAll(FORBIDDEN_TYPE_PATTERN)) {
    const matchIndex = match.index ?? 0;
    const typeToken = match[0];
    if (
      isTypePosition(line, matchIndex, typeToken.length) &&
      !tokens.includes(typeToken)
    ) {
      tokens.push(typeToken);
    }
  }

  return tokens;
}

/**
 * @param {string} line
 * @param {number} tokenStart
 * @param {number} tokenLength
 * @returns {boolean}
 */
function isTypePosition(line, tokenStart, tokenLength) {
  const previousIndex = previousNonWhitespaceIndex(line, tokenStart - 1);
  const nextIndex = nextNonWhitespaceIndex(line, tokenStart + tokenLength);
  const previousCharacter = previousIndex === -1 ? "" : line[previousIndex];
  const nextCharacter = nextIndex === -1 ? "" : line[nextIndex];

  return (
    previousCharacter !== "." && nextCharacter !== ":" && nextCharacter !== "?"
  );
}

/**
 * @param {string} line
 * @param {number} startIndex
 * @returns {number}
 */
function previousNonWhitespaceIndex(line, startIndex) {
  for (let index = startIndex; index >= 0; index -= 1) {
    const character = line[index];
    if (character !== undefined && !/\s/.test(character)) {
      return index;
    }
  }
  return -1;
}

/**
 * @param {string} line
 * @param {number} startIndex
 * @returns {number}
 */
function nextNonWhitespaceIndex(line, startIndex) {
  for (let index = startIndex; index < line.length; index += 1) {
    const character = line[index];
    if (character !== undefined && !/\s/.test(character)) {
      return index;
    }
  }
  return -1;
}

/**
 * @param {string | URL} [schemaPath]
 * @returns {Promise<string[]>}
 */
export async function readOpenApiTypeContractErrors(schemaPath = SCHEMA_URL) {
  const content = await readFile(schemaPath, "utf8");
  return validateOpenApiTypes(content, schemaPath.toString());
}

/**
 * @param {string} content
 * @param {string} [sourcePath]
 */
export function assertOpenApiTypes(content, sourcePath = "schema.d.ts") {
  const errors = validateOpenApiTypes(content, sourcePath);
  if (errors.length) {
    throw new Error(
      `Generated OpenAPI TypeScript contains forbidden any/unknown types:\n- ${errors.join("\n- ")}`,
    );
  }
}

/** @returns {Promise<void>} */
async function main() {
  const errors = await readOpenApiTypeContractErrors();
  if (errors.length) {
    throw new Error(
      `Generated OpenAPI TypeScript contains forbidden any/unknown types:\n- ${errors.join("\n- ")}`,
    );
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  await main();
}
