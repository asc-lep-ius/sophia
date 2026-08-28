import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  readOpenApiTypeContractErrors,
  validateOpenApiTypes,
} from "../../scripts/assert-openapi-types.mjs";

describe("generated OpenAPI type contract", () => {
  it("accepts generated schema content without forbidden fallback types", () => {
    expect(
      validateOpenApiTypes(
        "export interface operations { health: { headers: never; }; }\n",
        "schema.d.ts",
      ),
    ).toEqual([]);
  });

  it("ignores ordinary words in comments and string literals", () => {
    expect(
      validateOpenApiTypes(
        [
          "// unknown and any in comments are documentation, not types",
          "export type Label = 'unknown' | \"any\";",
          "export interface operations { health: { headers: never; }; }",
        ].join("\n"),
        "schema.d.ts",
      ),
    ).toEqual([]);
  });

  it("rejects generated schema content containing unknown", () => {
    expect(
      validateOpenApiTypes(
        [
          "export interface operations {",
          "  health: {",
          "    headers: { [name: string]: unknown; };",
          "  };",
          "}",
        ].join("\n"),
        "schema.d.ts",
      ),
    ).toEqual([
      "schema.d.ts:3 contains forbidden generated OpenAPI type `unknown`",
    ]);
  });

  it("rejects generated schema content containing any", () => {
    expect(
      validateOpenApiTypes(
        [
          "export type HeaderMap = Record<string, any>;",
          "export interface operations {",
          "  search: { responses: { 200: { content: { 'application/json': any[] } } } };",
          "}",
        ].join("\n"),
        "schema.d.ts",
      ),
    ).toEqual([
      "schema.d.ts:1 contains forbidden generated OpenAPI type `any`",
      "schema.d.ts:3 contains forbidden generated OpenAPI type `any`",
    ]);
  });

  it("checks a generated schema fixture from disk", async () => {
    const fixtureDir = await mkdtemp(join(tmpdir(), "sophia-openapi-types-"));
    const fixturePath = join(fixtureDir, "schema.d.ts");
    await writeFile(
      fixturePath,
      [
        "export type HeaderMap = { [name: string]: unknown };",
        "export type Payload = Record<string, any>;",
      ].join("\n"),
      "utf8",
    );

    await expect(readOpenApiTypeContractErrors(fixturePath)).resolves.toEqual([
      `${fixturePath}:1 contains forbidden generated OpenAPI type \`unknown\``,
      `${fixturePath}:2 contains forbidden generated OpenAPI type \`any\``,
    ]);
  });
});
