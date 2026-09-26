import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { ActionResult, SubmitFunction } from "@sveltejs/kit";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "../../src/routes/settings/+page.svelte";

/**
 * `enhance` stands in for the browser's round trip, holding every POST open
 * until the test answers it. That is what lets a test put two saves in flight
 * at once and choose the order they come back in.
 */
const harness = vi.hoisted(() => ({
  invalidated: undefined as (() => Promise<void> | void) | undefined,
  posts: [] as { body: FormData; answer: (result: ActionResult) => void }[],
}));

vi.mock("$app/forms", () => ({
  enhance(form: HTMLFormElement, submit: SubmitFunction) {
    const action = new URL("http://localhost/app/settings");
    const onSubmit = async (event: Event) => {
      event.preventDefault();
      let cancelled = false;
      const formData = new FormData(form);
      const settle = await submit({
        action,
        cancel: () => {
          cancelled = true;
        },
        controller: new AbortController(),
        formData,
        formElement: form,
        submitter: null,
      });
      if (cancelled) {
        return;
      }
      const result = await new Promise<ActionResult>((answer) => {
        harness.posts.push({ answer, body: formData });
      });
      await settle?.({
        action,
        formData,
        formElement: form,
        result,
        update: async () => undefined,
      });
    };
    form.addEventListener("submit", onSubmit);
    return { destroy: () => form.removeEventListener("submit", onSubmit) };
  },
}));

vi.mock("$app/navigation", () => ({
  invalidateAll: vi.fn(async () => harness.invalidated?.()),
}));

type Settings = { locale: "de" | "en"; theme: "dark" | "light" | "oled" };

describe("settings apply on change", () => {
  beforeEach(() => {
    harness.posts.length = 0;
    harness.invalidated = undefined;
    document.documentElement.dataset.theme = "light";
  });

  it("saves a theme the moment it is clicked, with no save button", async () => {
    const view = renderSettings({ locale: "en", theme: "light" });

    await fireEvent.click(radio("OLED"));

    expect(document.documentElement.dataset.theme).toBe("oled");
    expect(sent()).toEqual([{ locale: "en", theme: "oled" }]);
    expect(screen.queryByRole("button")).toBeNull();

    await view.answer(0, saved({ locale: "en", theme: "oled" }));

    expect((await screen.findByRole("status")).textContent).toContain(
      "Settings saved.",
    );
    expect(radio("OLED").checked).toBe(true);
    expect(document.documentElement.dataset.theme).toBe("oled");
  });

  it("stores the last of two overlapping clicks, not the last to arrive", async () => {
    const view = renderSettings({ locale: "en", theme: "light" });

    await fireEvent.click(radio("Dark"));
    await fireEvent.click(radio("OLED"));

    // The second click waits for the first save instead of racing it.
    expect(sent()).toEqual([{ locale: "en", theme: "dark" }]);
    expect(document.documentElement.dataset.theme).toBe("oled");

    await view.answer(0, saved({ locale: "en", theme: "dark" }));
    await waitFor(() => expect(sent()).toHaveLength(2));

    expect(sent()[1]).toEqual({ locale: "en", theme: "oled" });
    // Superseded, so it neither reports nor moves the controls back.
    expect(screen.queryByRole("status")).toBeNull();
    expect(radio("OLED").checked).toBe(true);

    await view.answer(1, saved({ locale: "en", theme: "oled" }));

    expect((await screen.findByRole("status")).textContent).toContain(
      "Settings saved.",
    );
    expect(radio("OLED").checked).toBe(true);
    expect(document.documentElement.dataset.theme).toBe("oled");
  });

  it("collapses every click made during one save into a single follow-up", async () => {
    const view = renderSettings({ locale: "en", theme: "light" });

    await fireEvent.click(radio("Dark"));
    await fireEvent.click(radio("OLED"));
    await fireEvent.click(radio("German"));
    await fireEvent.click(radio("Light"));

    await view.answer(0, saved({ locale: "en", theme: "dark" }));
    await waitFor(() => expect(sent()).toHaveLength(2));

    expect(sent()[1]).toEqual({ locale: "de", theme: "light" });
  });

  it("puts the page back to what the session holds when a save is refused", async () => {
    const view = renderSettings({ locale: "en", theme: "light" });

    await fireEvent.click(radio("OLED"));
    expect(document.documentElement.dataset.theme).toBe("oled");

    await view.answer(0, {
      data: { error: "save_failed" },
      status: 502,
      type: "failure",
    });

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Settings could not be saved.",
    );
    expect(radio("Light").checked).toBe(true);
    expect(isHighlighted(radio("OLED"))).toBe(false);
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("reports an error result on the page rather than leaving it pending", async () => {
    const view = renderSettings({ locale: "en", theme: "dark" });

    await fireEvent.click(radio("Light"));
    await view.answer(0, { error: new Error("offline"), type: "error" });

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Settings could not be saved.",
    );
    expect(radio("Dark").checked).toBe(true);
  });
});

/**
 * Renders the page over `stored`, and answers a POST the way the real stack
 * does: the action's result, then a data reload that returns whatever the
 * session record holds by then.
 */
function renderSettings(stored: Settings) {
  let session = stored;
  const view = render(SettingsPage, { props: { data: pageData(session) } });
  harness.invalidated = async () => {
    await view.rerender({ data: pageData(session) });
  };

  return {
    async answer(index: number, result: ActionResult) {
      if (result.type === "success") {
        session = (result.data as { settings: Settings }).settings;
      }
      harness.posts[index]?.answer(result);
      await Promise.resolve();
    },
  };
}

function pageData(settings: Settings) {
  return { locale: settings.locale, settings, theme: settings.theme };
}

function saved(settings: Settings): ActionResult {
  return { data: { settings }, status: 200, type: "success" };
}

function sent(): Record<string, string>[] {
  return harness.posts.map(({ body }) =>
    Object.fromEntries(
      [...body.entries()].map(([name, value]) => [name, String(value)]),
    ),
  );
}

function radio(name: string): HTMLInputElement {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

function isHighlighted(input: HTMLInputElement): boolean {
  return input.closest("label")?.classList.contains("active") ?? false;
}
