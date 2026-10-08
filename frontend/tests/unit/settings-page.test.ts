import { readFileSync } from "node:fs";
import { join } from "node:path";

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
          theme: "dark",
        }),
      ),
    });

    await expect(load(event as never)).resolves.toEqual({
      settings: {
        locale: "de",
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
        theme: "oled",
      }),
    );
    const event = createEvent({
      fetch,
      // What a page rendered before #106 would still post.
      form: {
        locale: "de",
        selected_learning_path_id: "course-2",
        theme: "oled",
      },
    });

    // Saving "de" over an English session reloads the page in German; what this
    // test is about is the PATCH underneath it. settings-locale.test.ts covers
    // the reload and the cookie behind it.
    await expect(settingsAction(event)).rejects.toMatchObject({
      location: "/app/settings",
      status: 303,
    });

    const init = fetch.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(fetch.mock.calls[0]?.[0]).toBe("/api/settings");
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe(
      JSON.stringify({
        locale: "de",
        theme: "oled",
      }),
    );
    expect(headers.get("x-requested-with")).toBe("fetch");
    expect(headers.get("x-csrf-token")).toBe("csrf-from-session");
  });

  it("pins the theme cookie once the session has taken the theme", async () => {
    const settingsAction = requireDefaultAction();
    const cookieSet = vi.fn();
    const event = createEvent({
      cookieSet,
      fetch: vi.fn().mockResolvedValue(
        jsonResponse({
          locale: "en",
          theme: "oled",
        }),
      ),
      form: { locale: "en", theme: "oled" },
    });

    await expect(settingsAction(event)).resolves.toEqual({
      settings: { locale: "en", theme: "oled" },
    });

    expect(cookieSet).toHaveBeenCalledWith(
      THEME_COOKIE,
      "oled",
      expect.objectContaining({ httpOnly: false, path: "/app" }),
    );
  });

  it("reports a refused save without claiming the refused values", async () => {
    const settingsAction = requireDefaultAction();
    const cookieSet = vi.fn();
    const event = createEvent({
      cookieSet,
      fetch: vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
      form: { locale: "en", theme: "oled" },
    });

    const result = await settingsAction(event);

    expect(result).toMatchObject({
      data: { error: "save_failed" },
      status: 502,
    });
    expect(result).not.toHaveProperty("data.settings");
    expect(cookieSet).not.toHaveBeenCalled();
  });

  it("answers an unreachable API as a failed save, not a thrown error", async () => {
    const settingsAction = requireDefaultAction();
    const event = createEvent({
      fetch: vi.fn().mockRejectedValue(new TypeError("fetch failed")),
      form: { locale: "en", theme: "oled" },
    });

    await expect(settingsAction(event)).resolves.toMatchObject({
      data: { error: "save_failed" },
      status: 502,
    });
  });

  it("keeps a submit button for browsers without JavaScript", () => {
    // Svelte renders <noscript> empty on the client, so the rendered page
    // cannot show it; the server-rendered markup is this source.
    const source = readFileSync(
      join(process.cwd(), "src/routes/settings/+page.svelte"),
      "utf8",
    );

    expect(source).toMatch(
      /<noscript>[\s\S]*<button type="submit">\{m\.settings_save\(\)\}<\/button>[\s\S]*<\/noscript>/,
    );
  });

  it("renders server-backed settings and repaints on click, with no save button", async () => {
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
    expect(
      document.querySelector('input[name="selected_learning_path_id"]'),
    ).toBeNull();

    await fireEvent.click(screen.getByRole("radio", { name: "OLED" }));

    expect(document.documentElement.dataset.theme).toBe("oled");
    expect(cookieValue).not.toContain(THEME_COOKIE);
    expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
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
  cookieSet = vi.fn(),
  fetch,
  form,
}: {
  cookieSet?: ReturnType<typeof vi.fn>;
  fetch: ReturnType<typeof vi.fn>;
  form?: Record<string, string>;
}): RequestEvent {
  const formData = new FormData();
  for (const [key, value] of Object.entries(form ?? {})) {
    formData.set(key, value);
  }

  return {
    cookies: { get: () => undefined, set: cookieSet },
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
    url: new URL("http://localhost/app/settings"),
  } as unknown as RequestEvent;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}
