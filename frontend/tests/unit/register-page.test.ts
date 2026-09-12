import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import RegisterPage from "../../src/routes/register/+page.svelte";
import { actions, load } from "../../src/routes/register/+page.server";
import type { CourseDetail } from "../../src/routes/register/+page.server";
import {
  isCourseNumber,
  parseTissInstant,
  registrationCountdown,
  type TissConnectionState,
  type TissFavorite,
  type TissGroup,
} from "../../src/lib/registration/tiss";
import type { Panel } from "../../src/lib/dashboard/panels";
import {
  createActionEvent,
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const REGISTER_URL = "http://localhost/app/register";
const NOW = new Date("2026-09-12T09:00:00Z");

describe("TISS helpers", () => {
  it("accepts the course-number shape TISS uses and nothing else", () => {
    expect(isCourseNumber("123.ABC")).toBe(true);
    expect(isCourseNumber("123.a1b")).toBe(true);
    expect(isCourseNumber("12.ABC")).toBe(false);
    expect(isCourseNumber("123-ABC")).toBe(false);
    expect(isCourseNumber("../../etc/passwd")).toBe(false);
  });

  /**
   * TISS prints a wall clock with no zone. Reading it in the browser's would
   * make the same window count down differently on two machines; pinning it to
   * UTC is one answer everywhere, which is what the legacy service did too.
   */
  it("reads a TISS timestamp as UTC rather than as local time", () => {
    expect(parseTissInstant("31.12.2026 08:00")?.toISOString()).toBe(
      "2026-12-31T08:00:00.000Z",
    );
    expect(parseTissInstant("not a date")).toBeNull();
    expect(parseTissInstant(null)).toBeNull();
  });

  it("counts down to a window and says when one is already open", () => {
    expect(registrationCountdown("13.09.2026 10:30", NOW)).toEqual({
      days: 1,
      hours: 1,
      minutes: 30,
      state: "waiting",
    });
    expect(registrationCountdown("01.09.2026 10:30", NOW).state).toBe("open");
    expect(registrationCountdown(null, NOW).state).toBe("unknown");
  });
});

describe("register server load", () => {
  it("opens a course only once TISS is actually reachable", async () => {
    const fetch = vi.fn(fetchFixture({ connection: "session_expired" }));

    const data = (await load(
      createLoadEvent({
        fetch,
        url: `${REGISTER_URL}?course=123.ABC`,
      }) as never,
    )) as RegisterData;

    expect(data.detail).toBeNull();
    expect(
      fetch.mock.calls.some((call) => String(call[0]).includes("/targets/")),
    ).toBe(false);
  });

  it("ignores a course number that is not one, without spending a request", async () => {
    const fetch = vi.fn(fetchFixture({}));

    const data = (await load(
      createLoadEvent({
        fetch,
        url: `${REGISTER_URL}?course=${encodeURIComponent("../secrets")}`,
      }) as never,
    )) as RegisterData;

    expect(data.selectedCourse).toBeNull();
    expect(
      fetch.mock.calls.some((call) => String(call[0]).includes("/targets/")),
    ).toBe(false);
  });

  it("loads the target, its groups and its exam dates together", async () => {
    const fetch = vi.fn(fetchFixture({}));

    const data = (await load(
      createLoadEvent({
        fetch,
        url: `${REGISTER_URL}?course=123.ABC`,
      }) as never,
    )) as RegisterData;

    expect(data.detail?.target?.course_number).toBe("123.ABC");
    expect(data.detail?.groups).toHaveLength(2);
    expect(data.detail?.exams).toHaveLength(1);
  });

  it("keeps a course readable when only its exam dates fail", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/exam-dates")
        ? new Response(null, { status: 502 })
        : fetchFixture({})(url),
    );

    const data = (await load(
      createLoadEvent({
        fetch,
        url: `${REGISTER_URL}?course=123.ABC`,
      }) as never,
    )) as RegisterData;

    expect(data.detail?.target).not.toBeNull();
    expect(data.detail?.exams).toEqual([]);
  });

  it("reports the favourites list as unavailable when TISS does not answer", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 502 }));

    const data = (await load(
      createLoadEvent({ fetch, url: REGISTER_URL }) as never,
    )) as RegisterData;

    expect(data.favorites.status).toBe("error");
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    await expect(
      load(
        createLoadEvent({
          authenticated: false,
          fetch: vi.fn(),
          url: REGISTER_URL,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/login", status: 303 });
  });
});

describe("register action", () => {
  it("refuses a malformed course number before it reaches TISS", async () => {
    const fetch = vi.fn();

    const result = await actions.register?.(
      createActionEvent({
        fetch,
        form: { course_number: "nope", group_id: "grp-1" },
        url: REGISTER_URL,
      }) as never,
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      data: { error: "course_number" },
      status: 422,
    });
  });

  /**
   * TISS answering "that group is full" is a successful call. Rendering it as
   * a transport failure would tell the learner to try again, which is exactly
   * the wrong advice.
   */
  it("carries a refusal from TISS through as a result, not as an error", async () => {
    const fetch = vi.fn(async () =>
      jsonResponse({
        connection: "connected",
        course_number: "123.ABC",
        result: {
          attempted_at: "2026-09-12T09:00:00Z",
          course_number: "123.ABC",
          group_name: "Gruppe B",
          message: "Gruppe ist voll",
          registration_type: "group",
          success: false,
        },
        semester: "2026W",
      }),
    );

    const result = await actions.register?.(
      createActionEvent({
        fetch,
        form: { course_number: "123.ABC", group_id: "grp-2" },
        url: REGISTER_URL,
      }) as never,
    );

    expect(result).toMatchObject({ result: { success: false } });
  });

  it("reports an expired session as one rather than as a refused registration", async () => {
    const fetch = vi.fn(async () =>
      jsonResponse({
        connection: "session_expired",
        course_number: "123.ABC",
        result: null,
        semester: "2026W",
      }),
    );

    const result = await actions.register?.(
      createActionEvent({
        fetch,
        form: { course_number: "123.ABC", group_id: "grp-1" },
        url: REGISTER_URL,
      }) as never,
    );

    expect(result).toMatchObject({ data: { error: "session" } });
  });
});

describe("register page", () => {
  it("names the missing connection and where to fix it", () => {
    render(RegisterPage, {
      data: pageData({ connection: "session_missing" }),
      form: null,
    });

    expect(screen.getByText("Not connected to TISS")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open settings" })).toBeTruthy();
  });

  it("separates an expired session from a missing one", () => {
    render(RegisterPage, {
      data: pageData({ connection: "session_expired" }),
      form: null,
    });

    expect(screen.getByText("TISS session expired")).toBeTruthy();
  });

  it("opens a course through a GET form, so the choice is a URL", () => {
    render(RegisterPage, {
      data: pageData({ favorites: { data: [favorite()], status: "ready" } }),
      form: null,
    });

    const open = screen.getByRole("button", { name: "Open this course" });
    const form = open.closest("form");
    expect(form?.getAttribute("method")).toBe("get");
    expect(
      form?.querySelector<HTMLInputElement>('input[name="course"]')?.value,
    ).toBe("123.ABC");
  });

  it("offers a register button only for a group that is open", () => {
    render(RegisterPage, {
      data: pageData({
        detail: detail(),
        favorites: { data: [favorite()], status: "ready" },
        selectedCourse: "123.ABC",
      }),
      form: null,
    });

    const buttons = screen.getAllByRole("button", { name: /^Register for/ });
    expect(buttons).toHaveLength(1);
    expect(buttons[0]?.textContent).toContain("Gruppe A");
    // The button names the place it takes, which is what replaces the legacy
    // confirmation dialog rather than dropping the confirmation entirely.
    expect(buttons[0]?.textContent).toContain("12 of 30 places taken");
  });

  /**
   * A bare `?/register` is resolved against the page URL and replaces its
   * whole query string, so the course would be gone by the time the action
   * answered — dropping the learner back on the favourites list, unable to see
   * whether the group filled or to try the next one.
   */
  it("keeps the open course in the action URL it submits to", () => {
    render(RegisterPage, {
      data: pageData({
        detail: detail(),
        favorites: { data: [favorite()], status: "ready" },
        selectedCourse: "123.ABC",
      }),
      form: null,
    });

    const action = screen
      .getAllByRole("button", { name: /^Register for/ })[0]
      ?.closest("form")
      ?.getAttribute("action");

    expect(action).toContain("course=123.ABC");
    expect(action).toContain("/register");
  });

  it("says when the registration window has not opened yet", () => {
    render(RegisterPage, {
      data: pageData({
        detail: detail(),
        favorites: { data: [favorite()], status: "ready" },
        selectedCourse: "123.ABC",
      }),
      form: null,
    });

    expect(screen.getByText(/Opens in/)).toBeTruthy();
  });

  it("reports a course TISS could not answer for", () => {
    render(RegisterPage, {
      data: pageData({
        detail: {
          courseNumber: "123.ABC",
          exams: [],
          groups: [],
          target: null,
        },
        favorites: { data: [favorite()], status: "ready" },
        selectedCourse: "123.ABC",
      }),
      form: null,
    });

    expect(screen.getByText(/did not answer for this course/)).toBeTruthy();
  });

  it("shows a refusal from TISS as a refusal, with the reason it gave", () => {
    render(RegisterPage, {
      data: pageData({ favorites: { data: [favorite()], status: "ready" } }),
      form: {
        result: {
          attempted_at: "2026-09-12T09:00:00Z",
          course_number: "123.ABC",
          group_name: "Gruppe B",
          message: "Gruppe ist voll",
          registration_type: "group",
          success: false,
        },
      },
    });

    expect(screen.getByRole("status").textContent).toContain("Gruppe ist voll");
  });

  it("says the favourites are outside the account's scope rather than empty", () => {
    render(RegisterPage, {
      data: pageData({ favorites: { data: [], status: "unauthorized" } }),
      form: null,
    });

    const panel = screen.getByRole("region", { name: "Favourites" });
    expect(
      within(panel).getByText(/outside what your account may read/),
    ).toBeTruthy();
    expect(within(panel).queryByText("No favourite courses")).toBeNull();
  });

  it("names an empty favourites list rather than leaving the page blank", () => {
    render(RegisterPage, { data: pageData({}), form: null });

    const panel = screen.getByRole("region", { name: "Favourites" });
    expect(within(panel).getByText("No favourite courses")).toBeTruthy();
  });
});

type RegisterData = {
  connection: TissConnectionState;
  detail: CourseDetail | null;
  favorites: Panel<TissFavorite[]>;
  now: string;
  selectedCourse: string | null;
};

function pageData(overrides: Partial<RegisterData>) {
  return {
    ...layoutData,
    connection: "connected" as TissConnectionState,
    detail: null,
    favorites: { data: [], status: "ready" } as Panel<TissFavorite[]>,
    now: NOW.toISOString(),
    selectedCourse: null,
    ...overrides,
  };
}

function favorite(): TissFavorite {
  return {
    course_number: "123.ABC",
    course_type: "VU",
    ects: 6,
    exam_registered: false,
    group_registered: false,
    hours: 4,
    lva_registered: true,
    semester: "2026W",
    title: "Algorithmen und Datenstrukturen",
  };
}

function group(id: string, name: string, status: string): TissGroup {
  return {
    capacity: 30,
    day: "Mo",
    enrolled: status === "open" ? 12 : 30,
    group_id: id,
    location: "Freihaus",
    name,
    status,
    time_end: "12:00",
    time_start: "10:00",
  };
}

function detail(): CourseDetail {
  const groups = [
    group("grp-1", "Gruppe A", "open"),
    group("grp-2", "Gruppe B", "full"),
  ];
  return {
    courseNumber: "123.ABC",
    exams: [],
    groups,
    target: {
      course_number: "123.ABC",
      groups,
      registration_end: "31.12.2099 20:00",
      registration_start: "31.12.2099 08:00",
      registration_type: "group",
      semester: "2026W",
      status: "open",
      title: "Algorithmen und Datenstrukturen",
    },
  };
}

function fetchFixture({
  connection = "connected",
}: {
  connection?: TissConnectionState;
}) {
  return async (url: string | URL): Promise<Response> => {
    const href = String(url);
    if (href.includes("/favorites")) {
      return jsonResponse({
        connection,
        favorites: [favorite()],
        semester: "2026W",
      });
    }
    if (href.includes("/exam-dates")) {
      return jsonResponse({
        course_number: "123.ABC",
        exams: [
          {
            course_number: "123.ABC",
            date_end: null,
            date_start: "15.01.2027 09:00",
            exam_id: "exam-1",
            mode: "written",
            registration_end: null,
            registration_start: null,
            title: "1. Termin",
          },
        ],
      });
    }
    if (href.includes("/groups")) {
      return jsonResponse({
        connection: "connected",
        course_number: "123.ABC",
        groups: detail().groups,
        semester: "2026W",
      });
    }
    return jsonResponse({
      connection: "connected",
      course_number: "123.ABC",
      semester: "2026W",
      target: detail().target,
    });
  };
}
