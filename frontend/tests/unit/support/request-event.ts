import type { RequestEvent } from "@sveltejs/kit";
import type { vi } from "vitest";

/**
 * A `RequestEvent` shaped just enough for a server load to run against.
 *
 * The long-tail surfaces (#101) each need one, and each needs to prove the
 * same two things: that the request is scoped from the session tenant rather
 * than from the query string, and that an unauthenticated visitor is sent to
 * sign in. Building it once keeps those assertions comparing the loads rather
 * than the scaffolding around them.
 */
export const TENANT_LEARNING_PATH = "12";

export type LoadEventOptions = {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  /** Overrides the tenant's learning path, for the "nothing selected" case. */
  learningPathId?: string;
  locale?: "de" | "en";
  url: string;
};

export function createLoadEvent({
  authenticated = true,
  fetch,
  learningPathId = TENANT_LEARNING_PATH,
  locale = "en",
  url,
}: LoadEventOptions): RequestEvent {
  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated,
      csrfToken: "csrf-from-session",
      learning_path_id: learningPathId,
      locale,
      org_id: "tu-wien",
      request_id: "req-longtail",
      role: "student",
      sessionSettings: null,
      tenant: {
        learning_path_id: learningPathId,
        org_id: "tu-wien",
        role: "student",
      },
      user: null,
    },
    request: new Request(url),
    url: new URL(url),
  } as unknown as RequestEvent;
}

/** An action event: a load event plus the submitted form body. */
export function createActionEvent(
  options: LoadEventOptions & { form: Record<string, string> },
): RequestEvent {
  const body = new FormData();
  for (const [name, value] of Object.entries(options.form)) {
    body.set(name, value);
  }
  const event = createLoadEvent(options);
  return {
    ...event,
    request: new Request(options.url, { body, method: "POST" }),
  } as unknown as RequestEvent;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status,
  });
}

/** The layout data every page component is rendered with. */
export const layoutData = {
  authenticated: true,
  locale: "en",
  settings: null,
  tenant: {
    learning_path_id: TENANT_LEARNING_PATH,
    org_id: "tu-wien",
    role: "student",
  },
  theme: "light",
  user: null,
} as const;
