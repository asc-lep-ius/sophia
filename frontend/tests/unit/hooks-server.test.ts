import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import {
  buildForwardedApiHeaders,
  hydrateAuthSessionLocals,
} from "../../src/hooks.server";

const CSRF_COOKIE = "__Host-sophia_csrf";

describe("server hook API helpers", () => {
  it("forwards cookies and request ids to backend API calls", () => {
    const event = createEvent({ cookieHeader: "sid=abc" });

    const headers = buildForwardedApiHeaders(event);

    expect(headers.get("cookie")).toBe("sid=abc");
    expect(headers.get("x-request-id")).toBe("req-123");
  });

  it("adds CSRF headers for unsafe API methods from hydrated locals", () => {
    const event = createEvent({ csrfToken: "csrf-from-session" });

    const headers = buildForwardedApiHeaders(event, undefined, "PATCH");

    expect(headers.get("x-requested-with")).toBe("fetch");
    expect(headers.get("x-csrf-token")).toBe("csrf-from-session");
  });

  it("falls back to the CSRF cookie when locals have not been hydrated", () => {
    const event = createEvent({
      cookieHeader: `${CSRF_COOKIE}=csrf-from-cookie`,
      csrfToken: null,
    });

    const headers = buildForwardedApiHeaders(event, undefined, "POST");

    expect(headers.get("x-requested-with")).toBe("fetch");
    expect(headers.get("x-csrf-token")).toBe("csrf-from-cookie");
  });

  it("preserves explicit caller headers for unsafe API methods", () => {
    const event = createEvent({ csrfToken: "csrf-from-session" });

    const headers = buildForwardedApiHeaders(
      event,
      {
        "x-csrf-token": "csrf-explicit",
        "x-requested-with": "xmlhttprequest",
      },
      "PATCH",
    );

    expect(headers.get("x-requested-with")).toBe("xmlhttprequest");
    expect(headers.get("x-csrf-token")).toBe("csrf-explicit");
  });

  it("hydrates authenticated session locals and re-emits API cookies", async () => {
    const event = createEvent({
      fetch: vi.fn().mockResolvedValue(
        jsonResponse(
          {
            authenticated: true,
            csrf_token: "csrf-from-api",
            settings: {
              locale: "de",
              selected_course_id: "course-2",
              theme: "dark",
            },
            tenant: {
              cohort_id: "cohort-a",
              course_id: "course-2",
              org_id: "tu-wien",
              role: "ta",
            },
            user: {
              display_name: "Learner One",
              email: "learner@example.test",
              id: "learner",
            },
          },
          { "set-cookie": "__Host-sophia_session=rotated; Path=/" },
        ),
      ),
    });

    await hydrateAuthSessionLocals(event);

    expect(event.fetch).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
    expect(event.locals.authenticated).toBe(true);
    expect(event.locals.user).toEqual({
      displayName: "Learner One",
      email: "learner@example.test",
      id: "learner",
      name: "Learner One",
    });
    expect(event.locals.tenant).toEqual({
      cohort_id: "cohort-a",
      course_id: "course-2",
      org_id: "tu-wien",
      role: "ta",
    });
    expect(event.locals.sessionSettings).toEqual({
      locale: "de",
      selected_course_id: "course-2",
      theme: "dark",
    });
    expect(event.locals.csrfToken).toBe("csrf-from-api");
    expect(event.locals.apiSetCookies).toContain(
      "__Host-sophia_session=rotated; Path=/",
    );
  });

  it("keeps anonymous fallback locals when the session API is unavailable", async () => {
    const event = createEvent({
      fetch: vi.fn().mockRejectedValue(new TypeError("api unavailable")),
    });

    await expect(hydrateAuthSessionLocals(event)).resolves.toBeUndefined();

    expect(event.locals.authenticated).toBe(false);
    expect(event.locals.user).toBeNull();
    expect(event.locals.tenant).toEqual({
      course_id: "default-course",
      org_id: "local",
      role: "student",
    });
    expect(event.locals.sessionSettings).toBeNull();
  });
});

function createEvent({
  cookieHeader,
  csrfToken = "csrf-local",
  fetch = vi.fn(),
}: {
  cookieHeader?: string;
  csrfToken?: string | null;
  fetch?: ReturnType<typeof vi.fn>;
} = {}): RequestEvent {
  const request = new Request("http://localhost/app/settings", {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  const cookieJar = parseCookies(cookieHeader);
  return {
    cookies: {
      get: (name: string) => cookieJar.get(name),
    },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated: false,
      course_id: "default-course",
      csrfToken,
      locale: "en",
      org_id: "local",
      request_id: "req-123",
      role: "student",
      sessionSettings: null,
      tenant: {
        course_id: "default-course",
        org_id: "local",
        role: "student",
      },
      user: null,
    },
    request,
  } as unknown as RequestEvent;
}

function jsonResponse(body: unknown, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json",
      ...headers,
    },
    status: 200,
  });
}

function parseCookies(cookieHeader?: string): Map<string, string> {
  const cookies = new Map<string, string>();
  for (const pair of cookieHeader?.split(";") ?? []) {
    const [rawName, ...rawValue] = pair.trim().split("=");
    if (rawName) {
      cookies.set(rawName, rawValue.join("="));
    }
  }
  return cookies;
}
