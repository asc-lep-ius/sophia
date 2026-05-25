import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_COOKIE } from "../../src/lib/theme";
import SettingsPage from "../../src/routes/settings/+page.svelte";

vi.mock("$app/state", () => ({
  page: {
    data: {
      theme: "dark",
    },
  },
}));

describe("settings theme controls", () => {
  let cookieValue = "";

  beforeEach(() => {
    cookieValue = "";
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.colorScheme = "light";
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => cookieValue,
      set: (value: string) => {
        cookieValue = value;
      },
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(document, "cookie");
  });

  it("reflects the layout theme and updates the cookie-backed document theme", async () => {
    render(SettingsPage);

    const darkRadio = screen.getByRole("radio", {
      name: "Dark",
    }) as HTMLInputElement;
    expect(darkRadio.checked).toBe(true);

    await fireEvent.click(screen.getByRole("radio", { name: "OLED" }));

    const oledRadio = screen.getByRole("radio", {
      name: "OLED",
    }) as HTMLInputElement;
    expect(oledRadio.checked).toBe(true);
    expect(cookieValue).toContain(`${THEME_COOKIE}=oled`);
    expect(cookieValue).toContain("Path=/app");
    expect(document.documentElement.dataset.theme).toBe("oled");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });
});
