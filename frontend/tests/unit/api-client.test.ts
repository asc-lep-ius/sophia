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
    expect(normalized.nested).toHaveLength(1);
    expect(normalized.nested.at(0)?.scheduled_at).toBeInstanceOf(Date);
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

  it("normalizes reserved-endpoint 501 responses", async () => {
    const body = { detail: { code: "feature.not_implemented", params: {} } };
    const response = new Response(JSON.stringify(body), {
      headers: { "x-request-id": "req-reserved" },
      status: 501,
    });

    await expect(
      unwrapApiResponse(
        Promise.resolve({ data: undefined, error: body, response }),
      ),
    ).rejects.toMatchObject({
      detail: { code: "feature.not_implemented", params: {} },
      requestId: "req-reserved",
      status: 501,
    });
  });

  it("normalizes engagement policy 412 params so the UI can name the missing step", () => {
    const error = normalizeApiError(
      {
        detail: {
          code: "engagement.policy_unmet",
          params: {
            missing_event_types: "elaboration_written",
            elaboration_chars: 4,
          },
        },
      },
      412,
    );

    expect(error.detail.code).toBe("engagement.policy_unmet");
    expect(error.detail.params.missing_event_types).toBe("elaboration_written");
    expect(error.detail.params.elaboration_chars).toBe(4);
  });
});
