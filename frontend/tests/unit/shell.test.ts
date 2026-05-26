import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import AppShell from "../../src/lib/components/AppShell.svelte";

const tenant = {
  course_id: "course-42",
  org_id: "tu-wien",
  role: "student",
};

const user = {
  displayName: "Learner One",
  email: "learner@example.test",
  id: "learner-1",
  name: "Learner One",
};

describe("app shell", () => {
  it("marks the desktop navigation item active for nested app routes", () => {
    render(AppShell, {
      activePath: "/app/study/session-1/act",
      authenticated: true,
      locale: "en",
      tenant,
      theme: "light",
      user,
    });

    expect(
      screen.getByRole("link", { name: "Study" }).getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Home" }).hasAttribute("aria-current"),
    ).toBe(false);
  });

  it("opens the mobile drawer, focuses close, closes from the button, and restores trigger focus", async () => {
    render(AppShell, {
      activePath: "/app/dashboard",
      authenticated: true,
      locale: "en",
      tenant,
      theme: "light",
      user,
    });

    const trigger = screen.getByRole("button", { name: "Open navigation" });
    trigger.focus();
    await fireEvent.click(trigger);

    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    expect(drawer).toBeTruthy();
    expect(within(drawer).getByRole("link", { name: "Settings" })).toBeTruthy();

    const close = screen.getByRole("button", { name: "Close navigation" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    await fireEvent.click(close);

    expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("closes the mobile drawer with Escape", async () => {
    render(AppShell, {
      activePath: "/app/dashboard",
      authenticated: true,
      locale: "en",
      tenant,
      theme: "light",
      user,
    });

    await fireEvent.click(
      screen.getByRole("button", { name: "Open navigation" }),
    );
    expect(screen.getByRole("dialog", { name: "Navigation" })).toBeTruthy();

    await fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
  });

  it("opens the command palette from the keyboard and filters route commands", async () => {
    render(AppShell, {
      activePath: "/app/study",
      authenticated: true,
      locale: "en",
      tenant,
      theme: "light",
      user,
    });

    await fireEvent.keyDown(window, { ctrlKey: true, key: "k" });

    const palette = screen.getByRole("dialog", { name: "Command palette" });
    expect(palette).toBeTruthy();
    const search = screen.getByLabelText("Search commands");
    await waitFor(() => expect(document.activeElement).toBe(search));
    expect(search.getAttribute("role")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();

    await fireEvent.input(search, { target: { value: "set" } });

    const settings = within(palette).getByRole("link", { name: "Settings" });
    expect(settings.getAttribute("href")).toBe("/app/settings");
    expect(within(palette).queryByRole("link", { name: "Study" })).toBeNull();

    await fireEvent.click(settings);

    expect(
      screen.queryByRole("dialog", { name: "Command palette" }),
    ).toBeNull();
  });

  it("renders authenticated shell metadata", () => {
    render(AppShell, {
      activePath: "/app/settings",
      authenticated: true,
      locale: "en",
      tenant,
      theme: "dark",
      user,
    });

    const sidebar = screen.getByRole("complementary", { name: "Sophia" });
    const topbar = screen.getByRole("banner", { name: "Session" });

    expect(within(topbar).getByText("Signed in")).toBeTruthy();
    expect(within(topbar).getByText("Learner One")).toBeTruthy();
    expect(within(sidebar).getByText("tu-wien")).toBeTruthy();
    expect(within(topbar).getByText("course-42")).toBeTruthy();
    expect(within(topbar).getByText("dark")).toBeTruthy();
  });
});
