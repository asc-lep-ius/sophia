import { paraglideMiddleware } from "$lib/paraglide/server";
import { getTextDirection } from "$lib/paraglide/runtime";
import type { ApiPath } from "$lib/api/client";
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

const DEFAULT_ORG_ID = "local";
const DEFAULT_COURSE_ID = "default-course";
const DEFAULT_ROLE = "student";

const contextHandle: Handle = async ({ event, resolve }) => {
  const requestId =
    event.request.headers.get("x-request-id")?.trim() || crypto.randomUUID();
  const locale = negotiateLocale(
    event.cookies.get(LOCALE_COOKIE) ?? event.cookies.get(SOPHIA_LOCALE_COOKIE),
    event.request.headers.get("accept-language"),
  );

  event.locals.user = null;
  event.locals.org_id = event.cookies.get("sophia-org-id") ?? DEFAULT_ORG_ID;
  event.locals.course_id =
    event.cookies.get("sophia-course-id") ?? DEFAULT_COURSE_ID;
  event.locals.role = DEFAULT_ROLE;
  event.locals.locale = locale;
  event.locals.tenant = {
    org_id: event.locals.org_id,
    course_id: event.locals.course_id,
    role: event.locals.role,
  };
  event.locals.request_id = requestId;
  event.locals.apiSetCookies = [];

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
  const headers = buildForwardedApiHeaders(event, init.headers);
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
): Headers {
  const headers = new Headers(initHeaders);
  const cookie = event.request.headers.get("cookie");
  if (cookie && !headers.has("cookie")) {
    headers.set("cookie", cookie);
  }
  if (!headers.has("x-request-id")) {
    headers.set("x-request-id", event.locals.request_id);
  }
  return headers;
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
