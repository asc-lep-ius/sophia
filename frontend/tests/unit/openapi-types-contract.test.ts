import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  readOpenApiTypeContractErrors,
  validateOpenApiTypes,
} from "../../scripts/assert-openapi-types.mjs";

describe("generated OpenAPI type contract", () => {
  it("accepts generated schema content without unknown types", () => {
    expect(
      validateOpenApiTypes(
        "export interface operations { health: { headers: never; }; }\n",
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
    ).toEqual(["schema.d.ts:3 contains forbidden `unknown` type"]);
  });

  it("checks a generated schema fixture from disk", async () => {
    const fixtureDir = await mkdtemp(join(tmpdir(), "sophia-openapi-types-"));
    const fixturePath = join(fixtureDir, "schema.d.ts");
    await writeFile(
      fixturePath,
      "export type HeaderMap = { [name: string]: unknown };\n",
      "utf8",
    );

    await expect(readOpenApiTypeContractErrors(fixturePath)).resolves.toEqual([
      `${fixturePath}:1 contains forbidden \`unknown\` type`,
    ]);
  });
});
