import { paraglideMiddleware } from "$lib/paraglide/server";
import { getTextDirection } from "$lib/paraglide/runtime";
import type { ApiPath } from "$lib/api/client";
import type { components } from "$lib/api/schema";
import {
  LOCALE_COOKIE,
  SOPHIA_LOCALE_COOKIE,
  negotiateLocale,
  type Locale,
} from "$lib/i18n/locale";
import type { Handle, RequestEvent } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

type ApiFetchInit = RequestInit & {
  headers?: HeadersInit;
};

type AuthSessionResponse = components["schemas"]["AuthSessionResponse"];
type SessionTenantResponse = components["schemas"]["SessionTenantResponse"];
type SessionUserResponse = components["schemas"]["SessionUserResponse"];
type SettingsResponse = components["schemas"]["SettingsResponse"];
type SophiaRole = "student" | "peer_instructor" | "ta" | "instructor";

const DEFAULT_ORG_ID = "local";
const DEFAULT_COURSE_ID = "default-course";
const DEFAULT_ROLE = "student";
const CSRF_COOKIE = "__Host-sophia_csrf";
const E2E_AUTH_COOKIE = "sophia-e2e-auth";
const E2E_AUTH_ENABLED = process.env.SOPHIA_E2E_AUTH === "1";
const SAFE_API_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);
const SOPHIA_ROLES = new Set<SophiaRole>([
  "student",
  "peer_instructor",
  "ta",
  "instructor",
]);

const contextHandle: Handle = async ({ event, resolve }) => {
  const requestId =
    event.request.headers.get("x-request-id")?.trim() || crypto.randomUUID();
  const locale = negotiateLocale(
    event.cookies.get(LOCALE_COOKIE) ?? event.cookies.get(SOPHIA_LOCALE_COOKIE),
    event.request.headers.get("accept-language"),
  );

  event.locals.authenticated = false;
  event.locals.user = null;
  event.locals.org_id = event.cookies.get("sophia-org-id") ?? DEFAULT_ORG_ID;
  event.locals.course_id =
    event.cookies.get("sophia-course-id") ?? DEFAULT_COURSE_ID;
  event.locals.role = DEFAULT_ROLE;
  event.locals.locale = locale;
  event.locals.csrfToken = csrfTokenFromCookie(event);
  event.locals.sessionSettings = null;
  event.locals.tenant = {
    org_id: event.locals.org_id,
    course_id: event.locals.course_id,
    role: event.locals.role,
  };
  event.locals.request_id = requestId;
  event.locals.apiSetCookies = [];

  await hydrateAuthSessionLocals(event);
  applyE2eAuthLocals(event);

  const response = await resolve(event);
  response.headers.set("x-request-id", requestId);
  for (const setCookie of event.locals.apiSetCookies) {
    response.headers.append("set-cookie", setCookie);
  }
  return response;
};

const paraglideHandle: Handle = ({ event, resolve }) =>
  paraglideMiddleware(
    event.request,
    ({ request: localizedRequest, locale }) => {
      event.request = localizedRequest;
      event.locals.locale = locale as Locale;
      return resolve(event, {
        transformPageChunk: ({ html }) =>
          html
            .replace("%lang%", locale)
            .replace("%dir%", getTextDirection(locale)),
      });
    },
  );

export const handle: Handle = sequence(contextHandle, paraglideHandle);

export async function apiFetch(
  event: RequestEvent,
  path: ApiPath,
  init: ApiFetchInit = {},
): Promise<Response> {
  const headers = buildForwardedApiHeaders(event, init.headers, init.method);
  const response = await event.fetch(path, {
    ...init,
    headers,
  });
  queueSetCookieReemission(event, response.headers);
  return response;
}

export function buildForwardedApiHeaders(
  event: RequestEvent,
  initHeaders?: HeadersInit,
  method?: string,
): Headers {
  const headers = new Headers(initHeaders);
  const cookie = event.request.headers.get("cookie");
  if (cookie && !headers.has("cookie")) {
    headers.set("cookie", cookie);
  }
  if (!headers.has("x-request-id")) {
    headers.set("x-request-id", event.locals.request_id);
  }
  if (isUnsafeApiMethod(method)) {
    if (!headers.has("x-requested-with")) {
      headers.set("x-requested-with", "fetch");
    }
    if (!headers.has("x-csrf-token")) {
      const csrfToken = event.locals.csrfToken ?? csrfTokenFromCookie(event);
      if (csrfToken) {
        headers.set("x-csrf-token", csrfToken);
      }
    }
  }
  return headers;
}

export async function hydrateAuthSessionLocals(
  event: RequestEvent,
): Promise<void> {
  try {
    const response = await apiFetch(event, "/api/auth/session");
    if (!response.ok) {
      return;
    }

    const body: unknown = await response.json();
    if (isAuthSessionResponse(body)) {
      applyAuthSessionLocals(event, body);
    }
  } catch {
    return;
  }
}

function applyE2eAuthLocals(event: RequestEvent): void {
  if (!E2E_AUTH_ENABLED || event.cookies.get(E2E_AUTH_COOKIE) !== "1") {
    return;
  }

  event.locals.authenticated = true;
  event.locals.csrfToken = event.locals.csrfToken ?? "e2e-csrf-token";
  event.locals.user = {
    displayName: "E2E Learner",
    email: "e2e@example.test",
    id: "e2e-learner",
    name: "E2E Learner",
  };
  event.locals.sessionSettings = {
    locale: event.locals.locale,
    selected_course_id: event.locals.course_id,
    theme: "light",
  };
}

function applyAuthSessionLocals(
  event: RequestEvent,
  session: AuthSessionResponse,
): void {
  event.locals.authenticated = session.authenticated;
  event.locals.csrfToken = session.csrf_token ?? event.locals.csrfToken;

  if (!session.authenticated) {
    event.locals.user = null;
    event.locals.sessionSettings = null;
    return;
  }

  if (isSessionUserResponse(session.user)) {
    event.locals.user = {
      displayName: session.user.display_name,
      email: session.user.email,
      id: session.user.id,
      name: session.user.display_name,
    };
  }

  if (isSessionTenantResponse(session.tenant)) {
    const role = normalizeRole(session.tenant.role);
    event.locals.org_id = session.tenant.org_id;
    event.locals.course_id = session.tenant.course_id;
    event.locals.role = role;
    event.locals.tenant = {
      cohort_id: session.tenant.cohort_id,
      org_id: session.tenant.org_id,
      course_id: session.tenant.course_id,
      role,
    };
  }

  if (isSettingsResponse(session.settings)) {
    event.locals.sessionSettings = session.settings;
  }
}

function isUnsafeApiMethod(method: string | undefined): boolean {
  return !SAFE_API_METHODS.has((method ?? "GET").toUpperCase());
}

function csrfTokenFromCookie(event: RequestEvent): string | null {
  return event.cookies.get(CSRF_COOKIE) ?? null;
}

function normalizeRole(role: string): SophiaRole {
  return SOPHIA_ROLES.has(role as SophiaRole)
    ? (role as SophiaRole)
    : DEFAULT_ROLE;
}

function isAuthSessionResponse(value: unknown): value is AuthSessionResponse {
  return (
    isRecord(value) &&
    typeof value.authenticated === "boolean" &&
    (value.csrf_token === null ||
      value.csrf_token === undefined ||
      typeof value.csrf_token === "string")
  );
}

function isSessionUserResponse(value: unknown): value is SessionUserResponse {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.display_name === "string" &&
    typeof value.email === "string"
  );
}

function isSessionTenantResponse(
  value: unknown,
): value is SessionTenantResponse {
  return (
    isRecord(value) &&
    typeof value.org_id === "string" &&
    typeof value.course_id === "string" &&
    typeof value.role === "string" &&
    (value.cohort_id === null ||
      value.cohort_id === undefined ||
      typeof value.cohort_id === "string")
  );
}

function isSettingsResponse(value: unknown): value is SettingsResponse {
  return (
    isRecord(value) &&
    typeof value.theme === "string" &&
    typeof value.locale === "string" &&
    (value.selected_course_id === null ||
      value.selected_course_id === undefined ||
      typeof value.selected_course_id === "string")
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function queueSetCookieReemission(event: RequestEvent, headers: Headers): void {
  for (const setCookie of getSetCookieHeaders(headers)) {
    event.locals.apiSetCookies.push(setCookie);
  }
}

function getSetCookieHeaders(headers: Headers): string[] {
  const headersWithSetCookie = headers as Headers & {
    getSetCookie?: () => string[];
  };
  const splitHeaders = headersWithSetCookie.getSetCookie?.();
  if (splitHeaders?.length) {
    return splitHeaders;
  }
  const singleHeader = headers.get("set-cookie");
  return singleHeader ? [singleHeader] : [];
}
