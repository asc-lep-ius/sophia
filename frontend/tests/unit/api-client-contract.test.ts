import { describe, expect, it } from "vitest";

import { validateApiClientContract } from "../../scripts/assert-api-client-contract.mjs";

const wrapperPath = "frontend/src/lib/api/client.ts";
const helperPath = "frontend/src/lib/api/lectures.ts";

const allowedWrapper = `
import createClient, { type ClientOptions } from "openapi-fetch";
import type { paths } from "./schema";

type ErrorEnvelope = {
  detail?: {
    code?: unknown;
    params?: unknown;
  };
};

export type ApiPath = keyof paths & string;

export function createApiClient(options: ClientOptions = {}) {
  return createClient<paths>({
    baseUrl: "",
    ...options,
  });
}

export function normalizeApiError(body: unknown) {
  const envelope = body as ErrorEnvelope;
  return envelope.detail?.code ?? "http.failed";
}
`;

describe("API client guard", () => {
  it("allows the single openapi-fetch wrapper and boundary unknown normalizers", () => {
    expect(
      validateApiClientContract([
        { path: wrapperPath, content: allowedWrapper },
      ]),
    ).toEqual([]);
  });

  it("rejects direct openapi-fetch imports outside the wrapper", () => {
    expect(
      validateApiClientContract([
        { path: wrapperPath, content: allowedWrapper },
        {
          path: helperPath,
          content:
            'import createClient from "openapi-fetch";\ncreateClient();\n',
        },
      ]),
    ).toContain(
      "frontend/src/lib/api/lectures.ts:1 imports openapi-fetch outside frontend/src/lib/api/client.ts",
    );
  });

  it("rejects as any casts", () => {
    expect(
      validateApiClientContract([
        {
          path: helperPath,
          content: "export const escaped = payload as any;\n",
        },
      ]),
    ).toContain("frontend/src/lib/api/lectures.ts:1 uses forbidden `as any`");
  });

  it("rejects manual response and body typing escape hatches", () => {
    expect(
      validateApiClientContract([
        {
          path: helperPath,
          content: [
            'client.GET<ManualResponse>("/api/lectures");',
            "const body = payload as BodyInit;",
            "const response = result as Response;",
          ].join("\n"),
        },
      ]),
    ).toEqual(
      expect.arrayContaining([
        "frontend/src/lib/api/lectures.ts:1 adds a manual OpenAPI method generic",
        "frontend/src/lib/api/lectures.ts:2 casts to BodyInit instead of generated request body types",
        "frontend/src/lib/api/lectures.ts:3 casts to Response instead of generated response types",
      ]),
    );
  });

  it("rejects dynamic OpenAPI path construction", () => {
    expect(
      validateApiClientContract([
        {
          path: helperPath,
          content: [
            "client.GET(`/api/lectures/${lectureId}`);",
            'client.POST("/api/" + resource);',
            "client.DELETE(path);",
            "const typedPath = route as ApiPath;",
          ].join("\n"),
        },
      ]),
    ).toEqual(
      expect.arrayContaining([
        "frontend/src/lib/api/lectures.ts:1 builds an OpenAPI path dynamically",
        "frontend/src/lib/api/lectures.ts:2 builds an OpenAPI path dynamically",
        "frontend/src/lib/api/lectures.ts:3 calls DELETE with a non-literal OpenAPI path",
        "frontend/src/lib/api/lectures.ts:4 casts to ApiPath instead of using a generated literal path",
      ]),
    );
  });
});
