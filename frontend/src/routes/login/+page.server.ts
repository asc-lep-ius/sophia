import { fail, redirect, type Actions, type RequestEvent } from "@sveltejs/kit";

import { apiFetch } from "../../hooks.server";
import type { PageServerLoad } from "./$types";

type LoginError = "invalid" | "required" | "unavailable";

export const load: PageServerLoad = ({ locals }) => {
  if (locals.authenticated) {
    redirect(303, "/app/dashboard");
  }

  return {};
};

export const actions: Actions = {
  default: async (event) => {
    const credentials = await readCredentials(event);
    if (!credentials.username || !credentials.password) {
      return fail(400, {
        error: "required" satisfies LoginError,
        username: credentials.username,
      });
    }

    const response = await apiFetch(event, "/api/auth/login", {
      body: JSON.stringify(credentials),
      headers: { "content-type": "application/json" },
      method: "POST",
    });

    if (response.ok) {
      redirect(303, "/app/dashboard");
    }

    return fail(loginFailureStatus(response.status), {
      error: loginFailureError(response.status),
      username: credentials.username,
    });
  },
};

async function readCredentials(event: RequestEvent) {
  const formData = await event.request.formData();
  return {
    password: readRawFormString(formData, "password"),
    username: readTrimmedFormString(formData, "username"),
  };
}

function readRawFormString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function readTrimmedFormString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function loginFailureStatus(status: number): 400 | 401 | 502 {
  if (status === 401 || status === 422) {
    return 401;
  }
  if (status >= 400 && status < 500) {
    return 400;
  }
  return 502;
}

function loginFailureError(status: number): LoginError {
  return status === 401 || status === 422 ? "invalid" : "unavailable";
}
