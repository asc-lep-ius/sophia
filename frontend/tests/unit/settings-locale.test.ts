import { fireEvent, render, screen } from "@testing-library/svelte";
import type { Handle, RequestEvent } from "@sveltejs/kit";
import { afterEach, describe, expect, it, vi } from "vitest";

import { paraglideHandle } from "../../src/hooks.server";
import {
  LOCALE_COOKIE,
  LOCALE_COOKIE_MAX_AGE,
  SOPHIA_LOCALE_COOKIE,
} from "../../src/lib/i18n/locale";
import { m } from "../../src/lib/paraglide/messages.js";
import { getLocale, overwriteGetLocale } from "../../src/lib/paraglide/runtime";
import { actions } from "../../src/routes/settings/+page.server";
import SettingsPage from "../../src/routes/settings/+page.svelte";

/**
 * #105 shipped with forty-odd green tests that only asserted the PATCH
 * returned 200, which is exactly what a saved-but-never-applied locale does.
 * These assert the three links of the chain instead: the click moves the
 * control, the save writes the cookie, and a request carrying that cookie comes
 * back in the other language.
 */
const DEFAULT_GET_LOCALE = getLocale;

describe("settings language control", () => {
  afterEach(() => {
    overwriteGetLocale(DEFAULT_GET_LOCALE);
  });

  it("moves its highlight to the language that was clicked", async () => {
    render(SettingsPage, { props: { data: pageData({ locale: "en" }) } });

    const english = radio("English");
    const german = radio("German");
    expect(english.checked).toBe(true);
    expect(isHighlighted(english)).toBe(true);

    await fireEvent.click(german);

    expect(german.checked).toBe(true);
    expect(isHighlighted(german)).toBe(true);
    expect(isHighlighted(english)).toBe(false);
  });

  it("highlights the language on the page when the session record disagrees", () => {
    render(SettingsPage, {
      props: {
        data: pageData({
          locale: "de",
          settings: {
            locale: "en",
            selected_learning_path_id: "12",
            theme: "light",
          },
        }),
      },
    });

    expect(isHighlighted(radio("German"))).toBe(true);
    expect(isHighlighted(radio("English"))).toBe(false);
  });

  it("renders the settings surface itself in the selected language", () => {
    overwriteGetLocale(() => "de");

    render(SettingsPage, { props: { data: pageData({ locale: "de" }) } });

    expect(
      screen.getByRole("button", { name: "Einstellungen speichern" }),
    ).toBeTruthy();
    expect(radio("Deutsch").checked).toBe(true);
    expect(screen.queryByRole("radio", { name: "German" })).toBeNull();
  });
});

describe("settings language save", () => {
  it("pins the Paraglide cookie and reloads when the language changes", async () => {
    const { cookieSet, event } = actionEvent({
      form: { locale: "de", selected_learning_path_id: "12", theme: "light" },
      locale: "en",
      saved: { locale: "de", selected_learning_path_id: "12", theme: "light" },
    });

    await expect(save(event)).rejects.toMatchObject({
      location: "/app/settings",
      status: 303,
    });

    expect(cookieSet).toHaveBeenCalledWith(LOCALE_COOKIE, "de", {
      httpOnly: false,
      maxAge: LOCALE_COOKIE_MAX_AGE,
      path: "/",
      sameSite: "lax",
      secure: false,
    });
  });

  it("pins the cookie without reloading when the language is unchanged", async () => {
    const saved = {
      locale: "en",
      selected_learning_path_id: "12",
      theme: "dark",
    };
    const { cookieSet, event } = actionEvent({
      form: { locale: "en", selected_learning_path_id: "12", theme: "dark" },
      locale: "en",
      saved,
    });

    await expect(save(event)).resolves.toEqual({ settings: saved });

    expect(cookieSet).toHaveBeenCalledWith(
      LOCALE_COOKIE,
      "en",
      expect.objectContaining({ path: "/" }),
    );
  });

  it("leaves the cookie alone when the API refuses the save", async () => {
    const { cookieSet, event } = actionEvent({
      form: { locale: "de", selected_learning_path_id: "12", theme: "light" },
      locale: "en",
      saved: { detail: "nope" },
      status: 422,
    });

    await expect(save(event)).resolves.toMatchObject({ status: 422 });

    expect(cookieSet).not.toHaveBeenCalled();
  });
});

describe("locale cookie on the next request", () => {
  it("renders in the language the cookie names", async () => {
    const event = hookEvent(`${LOCALE_COOKIE}=de`);

    const { localeLabel, transformed } = await renderThrough(event);

    expect(event.locals.locale).toBe("de");
    expect(localeLabel).toBe("Sprache");
    expect(transformed).toContain('lang="de"');
  });

  it("falls back to the base locale with no cookie and no preference", async () => {
    const event = hookEvent();

    const { localeLabel, transformed } = await renderThrough(event);

    expect(event.locals.locale).toBe("en");
    expect(localeLabel).toBe("Language");
    expect(transformed).toContain('lang="en"');
  });
});

/**
 * #114: the rows of the issue's table, through the same handle. The alias used
 * to be read by `contextHandle` and then overwritten here, so the first row
 * rendered in English.
 */
describe("sophia-locale alias on the next request", () => {
  it("renders in the language the alias names over the browser's preference", async () => {
    const event = hookEvent(`${SOPHIA_LOCALE_COOKIE}=de`, "en");

    const { localeLabel, transformed } = await renderThrough(event);

    expect(event.locals.locale).toBe("de");
    expect(localeLabel).toBe("Sprache");
    expect(transformed).toContain('lang="de"');
  });

  it("yields to the Paraglide cookie", async () => {
    const event = hookEvent(
      `${LOCALE_COOKIE}=en; ${SOPHIA_LOCALE_COOKIE}=de`,
      "de",
    );

    const { localeLabel, transformed } = await renderThrough(event);

    expect(event.locals.locale).toBe("en");
    expect(localeLabel).toBe("Language");
    expect(transformed).toContain('lang="en"');
  });

  it("falls through to the browser's preference when it names no locale", async () => {
    const event = hookEvent(`${SOPHIA_LOCALE_COOKIE}=fr`, "de-AT,de;q=0.9");

    const { localeLabel } = await renderThrough(event);

    expect(event.locals.locale).toBe("de");
    expect(localeLabel).toBe("Sprache");
  });
});

/**
 * Drives the real locale handle, capturing what a page render would have seen.
 *
 * `handle` itself cannot be called here: `sequence()` reads SvelteKit's internal
 * per-request store, which only exists inside a running server.
 */
async function renderThrough(
  event: RequestEvent,
): Promise<{ localeLabel: string; transformed: string }> {
  let localeLabel = "";
  let transformed = "";
  const resolve = vi.fn(
    async (
      _event: RequestEvent,
      options?: { transformPageChunk?: (input: { html: string }) => string },
    ) => {
      localeLabel = m.settings_locale_label();
      transformed =
        options?.transformPageChunk?.({
          html: '<html lang="%lang%" dir="%dir%">',
        }) ?? "";
      return new Response("<html></html>", {
        headers: { "content-type": "text/html" },
      });
    },
  );

  await (paraglideHandle as Handle)({ event, resolve } as never);
  return { localeLabel, transformed };
}

function save(event: RequestEvent) {
  const defaultAction = actions.default;
  if (!defaultAction) {
    throw new Error("settings default action is not configured");
  }
  return defaultAction(event as never);
}

function radio(name: string): HTMLInputElement {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

function isHighlighted(input: HTMLInputElement): boolean {
  return input.closest("label")?.classList.contains("active") ?? false;
}

function pageData({
  locale,
  settings,
}: {
  locale: "de" | "en";
  settings?: {
    locale: string;
    selected_learning_path_id?: string | null;
    theme: string;
  };
}) {
  return {
    locale,
    settings: settings ?? {
      locale,
      selected_learning_path_id: "12",
      theme: "light",
    },
    theme: "light" as const,
  };
}

function actionEvent({
  form,
  locale,
  saved,
  status = 200,
  url = "http://127.0.0.1:5173/app/settings",
}: {
  form: Record<string, string>;
  locale: "de" | "en";
  saved: unknown;
  status?: number;
  url?: string;
}): { cookieSet: ReturnType<typeof vi.fn>; event: RequestEvent } {
  const body = new FormData();
  for (const [name, value] of Object.entries(form)) {
    body.set(name, value);
  }
  const cookieSet = vi.fn();

  return {
    cookieSet,
    event: {
      cookies: { get: () => undefined, set: cookieSet },
      fetch: vi.fn().mockResolvedValue(
        new Response(JSON.stringify(saved), {
          headers: { "content-type": "application/json" },
          status,
        }),
      ),
      locals: {
        apiSetCookies: [],
        authenticated: true,
        csrfToken: "csrf-from-session",
        learning_path_id: "12",
        locale,
        org_id: "tu-wien",
        request_id: "req-settings-locale",
        role: "student",
        sessionSettings: {
          locale,
          selected_learning_path_id: "12",
          theme: "light",
        },
        tenant: { learning_path_id: "12", org_id: "tu-wien", role: "student" },
        user: null,
      },
      request: new Request(url, { body, method: "POST" }),
      url: new URL(url),
    } as unknown as RequestEvent,
  };
}

function hookEvent(
  cookieHeader?: string,
  acceptLanguage?: string,
): RequestEvent {
  const jar = new Map(
    (cookieHeader ?? "")
      .split("; ")
      .filter(Boolean)
      .map((pair) => {
        const [name, ...rest] = pair.split("=");
        return [name, rest.join("=")] as const;
      }),
  );

  return {
    cookies: { get: (name: string) => jar.get(name) },
    fetch: vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
    locals: { locale: "en" },
    request: new Request("http://localhost/app/settings", {
      headers: {
        ...(cookieHeader ? { cookie: cookieHeader } : {}),
        ...(acceptLanguage ? { "accept-language": acceptLanguage } : {}),
      },
    }),
  } as unknown as RequestEvent;
}
