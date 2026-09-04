import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import AppShell from "../../src/lib/components/AppShell.svelte";
import StudyPage from "../../src/routes/study/+page.svelte";

const tenant = {
  learning_path_id: "default-learning-path",
  org_id: "local",
  role: "student",
} as const;

const user = {
  displayName: "Smoke Tester",
  email: "smoke@example.test",
  id: "smoke-1",
  name: "Smoke Tester",
};

const layoutData = {
  authenticated: true,
  locale: "en",
  settings: null,
  theme: "light",
  tenant,
  user,
} as const;

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

  it("offers a session to start and one to resume", () => {
    render(StudyPage, {
      data: {
        ...layoutData,
        learningPathId: 12,
        sessions: [
          {
            id: 5,
            learning_path_id: 12,
            topic: "Graphs",
            pre_test_score: null,
            post_test_score: null,
            started_at: "2026-09-04T10:00:00Z",
            completed_at: null,
            improvement: null,
          },
        ],
      },
      form: null,
    });

    expect(screen.getByRole("heading", { name: "Study" })).toBeTruthy();
    expect(screen.getByLabelText("Topic")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start session" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Resume" }).getAttribute("href"),
    ).toBe("/app/study/5/act");
  });

  it("says so plainly when the workspace has no numeric learning path", () => {
    render(StudyPage, {
      data: { ...layoutData, learningPathId: null, sessions: [] },
      form: null,
    });

    expect(screen.queryByRole("button", { name: "Start session" })).toBeNull();
  });
});
