import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import AppShell from "../../src/lib/components/AppShell.svelte";
import StudyPage from "../../src/routes/study/+page.svelte";

const tenant = {
  course_id: "default-course",
  org_id: "local",
  role: "student",
};

describe("frontend scaffold smoke", () => {
  it("renders the authenticated app shell navigation", () => {
    render(AppShell, {
      activePath: "/app/study",
      locale: "en",
      tenant,
      theme: "light",
    });

    expect(
      screen.getByRole("link", { name: "Study" }).getAttribute("aria-current"),
    ).toBe("page");
    expect(screen.getByText("default-course")).toBeTruthy();
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
