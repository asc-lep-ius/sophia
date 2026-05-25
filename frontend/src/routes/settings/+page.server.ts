import { fail, redirect, type Actions, type RequestEvent } from "@sveltejs/kit";

import type { components } from "$lib/api/schema";
import { normalizeLocale } from "$lib/i18n/locale";
import { normalizeTheme } from "$lib/theme";
import { apiFetch } from "../../hooks.server";
import type { PageServerLoad } from "./$types";

type SettingsResponse = components["schemas"]["SettingsResponse"];
type SettingsFormError = "save_failed";

export const load: PageServerLoad = async (event) => {
  requireAuthenticated(event);

  let response: Response;
  try {
    response = await apiFetch(event, "/api/settings");
  } catch {
    return { settings: fallbackSettings(event) };
  }

  if (response.status === 401) {
    redirect(303, "/app/login");
  }
  if (!response.ok) {
    return { settings: fallbackSettings(event) };
  }

  try {
    return {
      settings: normalizeSettingsResponse(await response.json(), event),
    };
  } catch {
    return { settings: fallbackSettings(event) };
  }
};

export const actions: Actions = {
  default: async (event) => {
    requireAuthenticated(event);

    const settings = await settingsFromForm(event);
    const response = await apiFetch(event, "/api/settings", {
      body: JSON.stringify(settings),
      headers: { "content-type": "application/json" },
      method: "PATCH",
    });

    if (response.status === 401) {
      redirect(303, "/app/login");
    }
    if (!response.ok) {
      return fail(safeFailureStatus(response.status), {
        error: "save_failed" satisfies SettingsFormError,
        settings,
      });
    }

    return {
      settings: normalizeSettingsResponse(await response.json(), event),
    };
  },
};

function requireAuthenticated(event: RequestEvent): void {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }
}

async function settingsFromForm(
  event: RequestEvent,
): Promise<SettingsResponse> {
  const formData = await event.request.formData();
  const selectedCourseId = readOptionalFormString(
    formData,
    "selected_course_id",
  );
  return {
    locale:
      normalizeLocale(readFormString(formData, "locale")) ??
      event.locals.locale,
    selected_course_id: selectedCourseId,
    theme: normalizeTheme(readFormString(formData, "theme")),
  };
}

function normalizeSettingsResponse(
  value: unknown,
  event: RequestEvent,
): SettingsResponse {
  if (!isSettingsResponse(value)) {
    return fallbackSettings(event);
  }
  return value;
}

function fallbackSettings(event: RequestEvent): SettingsResponse {
  return {
    locale: event.locals.sessionSettings?.locale ?? event.locals.locale,
    selected_course_id:
      event.locals.sessionSettings?.selected_course_id ??
      event.locals.course_id,
    theme: event.locals.sessionSettings?.theme ?? "light",
  };
}

function readFormString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function readOptionalFormString(
  formData: FormData,
  name: string,
): string | null {
  const value = readFormString(formData, name);
  return value ? value : null;
}

function safeFailureStatus(status: number): 400 | 401 | 403 | 422 | 502 {
  if (status === 401 || status === 403 || status === 422) {
    return status;
  }
  if (status >= 400 && status < 500) {
    return 400;
  }
  return 502;
}

function isSettingsResponse(value: unknown): value is SettingsResponse {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as { theme?: unknown }).theme === "string" &&
    typeof (value as { locale?: unknown }).locale === "string" &&
    ((value as { selected_course_id?: unknown }).selected_course_id === null ||
      (value as { selected_course_id?: unknown }).selected_course_id ===
        undefined ||
      typeof (value as { selected_course_id?: unknown }).selected_course_id ===
        "string")
  );
}
