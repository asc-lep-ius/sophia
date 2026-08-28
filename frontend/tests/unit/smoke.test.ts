import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import AppShell from "../../src/lib/components/AppShell.svelte";
import StudyPage from "../../src/routes/study/+page.svelte";

const tenant = {
  learning_path_id: "default-learning-path",
  org_id: "local",
  role: "student",
};

const user = {
  displayName: "Smoke Tester",
  email: "smoke@example.test",
  id: "smoke-1",
  name: "Smoke Tester",
};

describe("frontend scaffold smoke", () => {
  it("renders the authenticated app shell navigation", () => {
    render(AppShell, {
      activePath: "/app/study",
      authenticated: true,
      locale: "en",
      tenant,
      theme: "light",
      user,
    });

    expect(
      screen.getByRole("link", { name: "Study" }).getAttribute("aria-current"),
    ).toBe("page");
    const sidebar = screen.getByRole("complementary", { name: "Sophia" });
    expect(within(sidebar).getByText("default-learning-path")).toBeTruthy();
  });

  it("renders the study controls with pointer equivalents", () => {
    render(StudyPage);

    expect(screen.getByRole("heading", { name: "Study" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reveal answer" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Undo last grade" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Again" })).toBeTruthy();
  });
});
