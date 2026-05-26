import { render, screen } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "../../src/routes/login/+page.svelte";
import { actions } from "../../src/routes/login/+page.server";

const ORIGINAL_API_BASE_URL = process.env.SOPHIA_API_BASE_URL;

describe("login route", () => {
  beforeEach(() => {
    delete process.env.SOPHIA_API_BASE_URL;
  });

  afterAll(() => {
    if (ORIGINAL_API_BASE_URL === undefined) {
      delete process.env.SOPHIA_API_BASE_URL;
      return;
    }

    process.env.SOPHIA_API_BASE_URL = ORIGINAL_API_BASE_URL;
  });

  it("renders an accessible localized credential form", () => {
    render(LoginPage);

    expect(
      screen.getByRole("heading", { level: 1, name: "Sign in" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("TU Wien account")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue" })).toHaveProperty(
      "type",
      "submit",
    );
  });

  it("posts trimmed username and exact submitted password to auth login", async () => {
    process.env.SOPHIA_API_BASE_URL = "http://api:8000";
    const loginAction = requireDefaultAction();
    const event = createActionEvent({
      fetch: vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ authenticated: true }), {
          headers: { "set-cookie": "__Host-sophia_session=signed; Path=/" },
          status: 200,
        }),
      ),
      form: {
        password: "  correct horse battery staple  ",
        username: "  learner@example.test  ",
      },
    });

    await expect(loginAction(event)).rejects.toMatchObject({
      location: "/app/dashboard",
      status: 303,
    });

    expect(event.fetch).toHaveBeenCalledWith(
      "http://api:8000/api/auth/login",
      expect.objectContaining({
        body: JSON.stringify({
          password: "  correct horse battery staple  ",
          username: "learner@example.test",
        }),
        method: "POST",
      }),
    );
    expect(event.locals.apiSetCookies).toContain(
      "__Host-sophia_session=signed; Path=/",
    );
  });

  it("preserves leading and trailing password spaces", async () => {
    const loginAction = requireDefaultAction();
    const event = createActionEvent({
      fetch: vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
      form: {
        password: "  padded password  ",
        username: "learner@example.test",
      },
    });

    await loginAction(event);

    expect(event.fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        body: JSON.stringify({
          password: "  padded password  ",
          username: "learner@example.test",
        }),
        method: "POST",
      }),
    );
  });

  it("returns a safe localized error state for invalid credentials", async () => {
    const loginAction = requireDefaultAction();
    const event = createActionEvent({
      fetch: vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ detail: { code: "auth.failed", params: {} } }),
            { status: 401 },
          ),
        ),
      form: {
        password: "wrong",
        username: "learner@example.test",
      },
    });

    const result = await loginAction(event);

    expect(result).toMatchObject({
      data: {
        error: "invalid",
        username: "learner@example.test",
      },
      status: 401,
    });

    render(LoginPage, { form: { error: "invalid" } });

    expect(
      screen.getByText("The account or password did not match."),
    ).toBeTruthy();
  });
});

function requireDefaultAction() {
  const defaultAction = actions.default;
  if (!defaultAction) {
    throw new Error("login default action is not configured");
  }
  return defaultAction;
}

function createActionEvent({
  fetch,
  form,
}: {
  fetch: ReturnType<typeof vi.fn>;
  form: Record<string, string>;
}): RequestEvent {
  const formData = new FormData();
  for (const [key, value] of Object.entries(form)) {
    formData.set(key, value);
  }

  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated: false,
      course_id: "default-course",
      csrfToken: null,
      locale: "en",
      org_id: "local",
      request_id: "req-login",
      role: "student",
      sessionSettings: null,
      tenant: {
        course_id: "default-course",
        org_id: "local",
        role: "student",
      },
      user: null,
    },
    request: new Request("http://localhost/app/login", {
      body: formData,
      method: "POST",
    }),
  } as unknown as RequestEvent;
}
