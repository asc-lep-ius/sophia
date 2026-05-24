import { describe, expect, it } from "vitest";

import {
  normalizeApiError,
  normalizeIsoDatetimes,
  unwrapApiResponse,
} from "../../src/lib/api/client";

describe("API client normalization", () => {
  it("normalizes FastAPI error envelopes with request IDs", () => {
    const error = normalizeApiError(
      { detail: { code: "auth.failed", params: { provider: "tuwel" } } },
      401,
      "req-123",
    );

    expect(error).toEqual({
      detail: { code: "auth.failed", params: { provider: "tuwel" } },
      requestId: "req-123",
      status: 401,
    });
  });

  it("falls back to http.failed for non-envelope errors", () => {
    expect(normalizeApiError("bad gateway", 502)).toEqual({
      detail: { code: "http.failed", params: {} },
      requestId: undefined,
      status: 502,
    });
  });

  it("turns ISO datetimes into Date values without touching plain strings", () => {
    const normalized = normalizeIsoDatetimes({
      created_at: "2026-05-24T10:30:00Z",
      name: "2026-05-24",
      nested: [{ scheduled_at: "2026-05-24T12:00:00+02:00" }],
    });

    expect(normalized.created_at).toBeInstanceOf(Date);
    expect(normalized.name).toBe("2026-05-24");
    expect(normalized.nested[0].scheduled_at).toBeInstanceOf(Date);
  });

  it("throws SophiaApiError from openapi-fetch error results", async () => {
    const response = new Response(
      JSON.stringify({ detail: { code: "http.not_found" } }),
      {
        headers: { "x-request-id": "req-missing" },
        status: 404,
      },
    );

    await expect(
      unwrapApiResponse(
        Promise.resolve({
          data: undefined,
          error: { detail: { code: "http.not_found" } },
          response,
        }),
      ),
    ).rejects.toMatchObject({
      detail: { code: "http.not_found", params: {} },
      requestId: "req-missing",
      status: 404,
    });
  });
});
