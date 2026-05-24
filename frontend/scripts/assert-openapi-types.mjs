import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const SCHEMA_URL = new URL("../src/lib/api/schema.d.ts", import.meta.url);
const UNKNOWN_TYPE_PATTERN = /\bunknown\b/;

/**
 * @param {string} content
 * @param {string} [sourcePath]
 * @returns {string[]}
 */
export function validateOpenApiTypes(content, sourcePath = "schema.d.ts") {
  return content
    .split(/\r?\n/)
    .flatMap((line, index) =>
      UNKNOWN_TYPE_PATTERN.test(line)
        ? [`${sourcePath}:${index + 1} contains forbidden \`unknown\` type`]
        : [],
    );
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
      `Generated OpenAPI TypeScript contains forbidden unknown types:\n- ${errors.join("\n- ")}`,
    );
  }
}

/** @returns {Promise<void>} */
async function main() {
  const errors = await readOpenApiTypeContractErrors();
  if (errors.length) {
    throw new Error(
      `Generated OpenAPI TypeScript contains forbidden unknown types:\n- ${errors.join("\n- ")}`,
    );
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  await main();
}
