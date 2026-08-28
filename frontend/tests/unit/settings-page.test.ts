import { fireEvent, render, screen } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import { THEME_COOKIE } from "../../src/lib/theme";
import SettingsPage from "../../src/routes/settings/+page.svelte";
import { actions, load } from "../../src/routes/settings/+page.server";

describe("settings route", () => {
  it("loads authenticated settings through apiFetch", async () => {
    const event = createEvent({
      fetch: vi.fn().mockResolvedValue(
        jsonResponse({
          locale: "de",
          selected_learning_path_id: "course-2",
          theme: "dark",
        }),
      ),
    });

    await expect(load(event as never)).resolves.toEqual({
      settings: {
        locale: "de",
        selected_learning_path_id: "course-2",
        theme: "dark",
      },
    });

    expect(event.fetch).toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("redirects to login when the settings API rejects the session", async () => {
    const event = createEvent({
      fetch: vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
    });

    await expect(load(event as never)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });

  it("persists settings with CSRF headers through the central API helper", async () => {
    const settingsAction = requireDefaultAction();
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        locale: "de",
        selected_learning_path_id: "course-2",
        theme: "oled",
      }),
    );
    const event = createEvent({
      fetch,
      form: {
        locale: "de",
        selected_learning_path_id: "course-2",
        theme: "oled",
      },
    });

    await expect(settingsAction(event)).resolves.toEqual({
      settings: {
        locale: "de",
        selected_learning_path_id: "course-2",
        theme: "oled",
      },
    });

    const init = fetch.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(fetch.mock.calls[0]?.[0]).toBe("/api/settings");
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe(
      JSON.stringify({
        locale: "de",
        selected_learning_path_id: "course-2",
        theme: "oled",
      }),
    );
    expect(headers.get("x-requested-with")).toBe("fetch");
    expect(headers.get("x-csrf-token")).toBe("csrf-from-session");
  });

  it("renders server-backed settings and applies theme feedback before submit", async () => {
    let cookieValue = "";
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => cookieValue,
      set: (value: string) => {
        cookieValue = value;
      },
    });
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.colorScheme = "light";

    render(SettingsPage, {
      props: {
        data: {
          locale: "en",
          settings: {
            locale: "en",
            selected_learning_path_id: "course-1",
            theme: "dark",
          },
          theme: "light",
        },
      },
    });

    const darkRadio = screen.getByRole("radio", {
      name: "Dark",
    }) as HTMLInputElement;
    expect(darkRadio.checked).toBe(true);

    await fireEvent.click(screen.getByRole("radio", { name: "OLED" }));

    expect(cookieValue).toContain(`${THEME_COOKIE}=oled`);
    expect(document.documentElement.dataset.theme).toBe("oled");
    expect(
      screen.getByRole("button", { name: "Save settings" }),
    ).toHaveProperty("type", "submit");
  });
});

function requireDefaultAction() {
  const defaultAction = actions.default;
  if (!defaultAction) {
    throw new Error("settings default action is not configured");
  }
  return defaultAction;
}

function createEvent({
  fetch,
  form,
}: {
  fetch: ReturnType<typeof vi.fn>;
  form?: Record<string, string>;
}): RequestEvent {
  const formData = new FormData();
  for (const [key, value] of Object.entries(form ?? {})) {
    formData.set(key, value);
  }

  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated: true,
      learning_path_id: "course-1",
      csrfToken: "csrf-from-session",
      locale: "en",
      org_id: "tu-wien",
      request_id: "req-settings",
      role: "student",
      sessionSettings: {
        locale: "en",
        selected_learning_path_id: "course-1",
        theme: "dark",
      },
      tenant: {
        learning_path_id: "course-1",
        org_id: "tu-wien",
        role: "student",
      },
      user: {
        displayName: "Learner One",
        email: "learner@example.test",
        id: "learner",
        name: "Learner One",
      },
    },
    request: new Request("http://localhost/app/settings", {
      body: form ? formData : undefined,
      method: form ? "POST" : "GET",
    }),
  } as unknown as RequestEvent;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}
