import { describe, expect, it } from "vitest";

import { validateOpenApiTypes } from "../../scripts/assert-openapi-types.mjs";
import { normalizeOpenApiTypesContent } from "../../scripts/normalize-openapi-types.mjs";

describe("OpenAPI type normalizer", () => {
  it("normalizes FastAPI validation error input fallback to a strict type", () => {
    const content = [
      "export interface components {",
      "  schemas: {",
      "    /** ValidationError */",
      "    ValidationError: {",
      "      /** Input */",
      "      input?: unknown;",
      "      /** Location */",
      "      loc: (string | number)[];",
      "    };",
      "  };",
      "}",
    ].join("\n");

    const normalized = normalizeOpenApiTypesContent(content);

    expect(normalized.content).toContain("      input?: never;");
    expect(normalized.content).not.toContain("input?: unknown;");
    expect(validateOpenApiTypes(normalized.content, "schema.d.ts")).toEqual([]);
  });

  it("keeps unrelated unknown input fields visible to the guard", () => {
    const content = [
      "export interface components {",
      "  schemas: {",
      "    CustomError: {",
      "      input?: unknown;",
      "    };",
      "  };",
      "}",
    ].join("\n");

    const normalized = normalizeOpenApiTypesContent(content);

    expect(normalized.content).toBe(content);
    expect(validateOpenApiTypes(normalized.content, "schema.d.ts")).toEqual([
      "schema.d.ts:4 contains forbidden generated OpenAPI type `unknown`",
    ]);
  });
});
