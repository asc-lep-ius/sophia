import { render, screen, within } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import ContentPage from "../../src/routes/content/+page.svelte";
import { load } from "../../src/routes/content/+page.server";
import type { ContentItem, ContentSource } from "../../src/lib/content/filters";
import type { ContentLanguageState } from "../../src/lib/content/language";
import type { Panel } from "../../src/lib/dashboard/panels";

const TENANT_LEARNING_PATH = "12";

describe("content server load", () => {
  it("defaults content to the course language while the chrome stays English", async () => {
    // The acceptance case: exam language de, UI preference en, no ?lang=.
    const event = createEvent({
      fetch: vi.fn(fetchFixture({ language: "de" })),
    });

    const data = (await load(event as never)) as ContentData;

    expect(data.contentLanguage).toEqual({
      language: "de",
      origin: "learning_path",
      override: null,
    });
    expect(data.uiLocale).toBe("en");
  });

  it("never asks for a content language the learner did not choose", async () => {
    const fetch = vi.fn(fetchFixture({ language: "de" }));
    await load(createEvent({ fetch }) as never);

    const languageCall = fetch.mock.calls
      .map((call) => String(call[0]))
      .find((url) => url.includes("/content-language"));

    expect(languageCall).toBeDefined();
    expect(languageCall).not.toContain("lang=");
  });

  it("passes an explicit ?lang= through as an override", async () => {
    const fetch = vi.fn(fetchFixture({ language: "en", origin: "override" }));
    const event = createEvent({
      fetch,
      url: "http://localhost/app/content?lang=en",
    });

    const data = (await load(event as never)) as ContentData;

    expect(data.contentLanguage.override).toBe("en");
    expect(
      fetch.mock.calls
        .map((call) => String(call[0]))
        .find((url) => url.includes("/content-language")),
    ).toContain("lang=en");
  });

  it("falls back to the deployment default, never to the UI locale", async () => {
    // A German course read through an English interface must not become an
    // English course because the language service was unreachable.
    const event = createEvent({
      fetch: vi.fn(async (url: string) =>
        String(url).includes("/content-language")
          ? new Response(null, { status: 503 })
          : fetchFixture({ language: "de" })(url),
      ),
    });

    const data = (await load(event as never)) as ContentData;

    expect(data.contentLanguage.language).toBe("de");
    expect(data.uiLocale).toBe("en");
  });

  it("applies the URL's filters before the first paint", async () => {
    const event = createEvent({
      fetch: vi.fn(fetchFixture({ language: "de" })),
      url: "http://localhost/app/content?status=ready",
    });

    const data = (await load(event as never)) as ContentData;

    expect(data.filters.status).toBe("ready");
    expect(
      data.groups.flatMap((group) => group.items.map((item) => item.id)),
    ).toEqual(["item-ready"]);
  });

  it("keeps the catalogue readable when one source's items fail", async () => {
    const event = createEvent({
      fetch: vi.fn(async (url: string) =>
        String(url).includes("/content-sources/12/content-items")
          ? new Response(null, { status: 500 })
          : fetchFixture({ language: "de" })(url),
      ),
    });

    const data = (await load(event as never)) as ContentData;

    expect(data.sources.status).toBe("ready");
    expect(data.groups).toEqual([]);
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    const event = createEvent({ authenticated: false, fetch: vi.fn() });

    await expect(load(event as never)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });
});

describe("content page", () => {
  it("names both languages so neither can be mistaken for the other", () => {
    render(ContentPage, {
      data: pageData({
        contentLanguage: {
          language: "de",
          origin: "learning_path",
          override: null,
        },
      }),
    });

    const notice = screen.getByRole("complementary", {
      name: "Languages on this page",
    });
    expect(within(notice).getByText("Deutsch")).toBeTruthy();
    expect(within(notice).getByText("English")).toBeTruthy();
    expect(
      within(notice).getByText(/language the course is examined in/),
    ).toBeTruthy();
  });

  it("carries the chosen content language onto the next page", () => {
    render(ContentPage, {
      data: pageData({
        contentLanguage: { language: "en", origin: "override", override: "en" },
      }),
    });

    const carried = document.querySelectorAll<HTMLInputElement>(
      'input[type="hidden"][name="lang"]',
    );
    expect(carried.length).toBeGreaterThan(0);
    expect([...carried].every((input) => input.value === "en")).toBe(true);
  });

  it("offers the next action on an empty catalogue", () => {
    render(ContentPage, { data: pageData({}) });

    expect(screen.getByText("No lectures yet")).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: "Add or sync lectures" }).length,
    ).toBeGreaterThan(0);
  });

  it("distinguishes a filtered-out catalogue from an empty one", () => {
    render(ContentPage, {
      data: pageData({ filters: { query: "graphs", status: "all" } }),
    });

    expect(screen.getByText("Nothing matches those filters")).toBeTruthy();
    expect(screen.queryByText("No lectures yet")).toBeNull();
  });

  it("says a source could not be read rather than showing it as empty", () => {
    render(ContentPage, {
      data: pageData({ sources: { data: [], status: "error" } }),
    });

    const panel = screen.getByRole("region", { name: "Lecture catalogue" });
    expect(within(panel).getByText(/did not answer/)).toBeTruthy();
    expect(within(panel).queryByText("No lectures yet")).toBeNull();
  });

  it("names the stage each item is waiting on", () => {
    render(ContentPage, {
      data: pageData({
        groups: [
          {
            itemCount: 2,
            items: [
              contentItem("item-ready", true),
              contentItem("item-pending", false),
            ],
            readyCount: 1,
            source: { external_ref: "series-12", id: 12, title: "Algorithms" },
          },
        ],
      }),
    });

    expect(screen.getByText("Ready")).toBeTruthy();
    expect(screen.getByText("Transcribing")).toBeTruthy();
  });
});

type ContentData = {
  contentLanguage: ContentLanguageState;
  drawerOpen: boolean;
  filters: { query: string; status: "all" | "pending" | "ready" };
  groups: {
    itemCount: number;
    items: ContentItem[];
    readyCount: number;
    source: ContentSource;
  }[];
  sourceCount: number;
  sources: Panel<ContentSource[]>;
  uiLocale: "de" | "en";
};

const layoutData = {
  authenticated: true,
  locale: "en",
  settings: null,
  tenant: {
    learning_path_id: TENANT_LEARNING_PATH,
    org_id: "tu-wien",
    role: "student",
  },
  theme: "light",
  user: null,
} as const;

function pageData(overrides: Partial<ContentData>) {
  return {
    ...layoutData,
    contentLanguage: {
      language: "de",
      origin: "learning_path",
      override: null,
    } satisfies ContentLanguageState,
    drawerOpen: false,
    filters: { query: "", status: "all" as const },
    groups: [],
    sourceCount: 0,
    sources: { data: [], status: "ready" } as Panel<ContentSource[]>,
    uiLocale: "en" as const,
    ...overrides,
  };
}

function contentItem(id: string, ready: boolean): ContentItem {
  return {
    download_status: "completed",
    id,
    index_status: ready ? "completed" : "pending",
    missed_at: null,
    sequence_number: 1,
    skip_reason: null,
    title: `Lecture ${id}`,
    transcription_status: ready ? "completed" : "pending",
  };
}

function fetchFixture({
  language,
  origin = "learning_path",
}: {
  language: "de" | "en";
  origin?: "default" | "learning_path" | "override";
}) {
  return async (url: string | URL): Promise<Response> => {
    const href = String(url);
    if (href.includes("/content-language")) {
      return jsonResponse({
        available_translations: [],
        content_language: language,
        learning_path_id: 12,
        resolved_from: origin,
      });
    }
    if (href.includes("/content-items")) {
      return jsonResponse({
        content_source_id: 12,
        items: [
          contentItem("item-ready", true),
          contentItem("item-pending", false),
        ],
      });
    }
    return jsonResponse({
      sources: [{ external_ref: "series-12", id: 12, title: "Algorithms" }],
    });
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

function createEvent({
  authenticated = true,
  fetch,
  url = "http://localhost/app/content",
}: {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  url?: string;
}): RequestEvent {
  return {
    cookies: { get: () => undefined },
    fetch,
    locals: {
      apiSetCookies: [],
      authenticated,
      csrfToken: "csrf-from-session",
      learning_path_id: TENANT_LEARNING_PATH,
      locale: "en",
      org_id: "tu-wien",
      request_id: "req-content",
      role: "student",
      sessionSettings: null,
      tenant: {
        learning_path_id: TENANT_LEARNING_PATH,
        org_id: "tu-wien",
        role: "student",
      },
      user: null,
    },
    request: new Request(url),
    url: new URL(url),
  } as unknown as RequestEvent;
}
