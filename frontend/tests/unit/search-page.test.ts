import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import SearchPage from "../../src/routes/search/+page.svelte";
import { load } from "../../src/routes/search/+page.server";
import {
  formatTimestamp,
  scoreBand,
  readSourceFilter,
  type SearchResult,
} from "../../src/lib/search/results";
import type { ContentSource } from "../../src/lib/content/filters";
import type { Panel } from "../../src/lib/dashboard/panels";
import {
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const SEARCH_URL = "http://localhost/app/search";

describe("search results helpers", () => {
  it("writes a timestamp the way the legacy page did", () => {
    expect(formatTimestamp(0)).toBe("00:00");
    expect(formatTimestamp(65)).toBe("01:05");
    expect(formatTimestamp(3725)).toBe("1:02:05");
    expect(formatTimestamp(-10)).toBe("00:00");
  });

  /**
   * A vector distance is not a probability that the passage answers the
   * question. Bands say what the number is worth; a percentage would invite a
   * precision the index cannot support.
   */
  it("bands a relevance score instead of printing it as a percentage", () => {
    expect(scoreBand(0.9)).toBe("strong");
    expect(scoreBand(0.7)).toBe("strong");
    expect(scoreBand(0.5)).toBe("moderate");
    expect(scoreBand(0.39)).toBe("weak");
  });

  it("falls back to every kind for a filter it does not recognise", () => {
    expect(readSourceFilter("document")).toBe("document");
    expect(readSourceFilter("nonsense")).toBe("all");
    expect(readSourceFilter(null)).toBe("all");
  });
});

describe("search server load", () => {
  it("answers a submitted query on the server, before anything hydrates", async () => {
    const fetch = vi.fn(fetchFixture());

    const data = (await load(
      createLoadEvent({ fetch, url: `${SEARCH_URL}?q=graph` }) as never,
    )) as SearchData;

    const searchCall = fetch.mock.calls.find((call) =>
      String(call[0]).includes("/api/search"),
    );
    expect(searchCall).toBeTruthy();
    expect(
      JSON.parse(String((searchCall?.[1] as RequestInit).body)),
    ).toMatchObject({
      content_source_id: 12,
      learning_path_id: 12,
      query: "graph",
    });
    expect(data.results?.data).toHaveLength(1);
  });

  it("asks for nothing when no query was submitted", async () => {
    const fetch = vi.fn(fetchFixture());

    const data = (await load(
      createLoadEvent({ fetch, url: SEARCH_URL }) as never,
    )) as SearchData;

    expect(
      fetch.mock.calls.some((call) => String(call[0]).includes("/api/search")),
    ).toBe(false);
    // Null, not an empty panel: nothing asked and nothing found are different
    // things, and an empty list cannot tell them apart.
    expect(data.results).toBeNull();
  });

  it("refuses to forward a source the learner does not have", async () => {
    const fetch = vi.fn(fetchFixture());

    const data = (await load(
      createLoadEvent({
        fetch,
        url: `${SEARCH_URL}?q=graph&source=999`,
      }) as never,
    )) as SearchData;

    expect(data.selectedSourceId).toBe(12);
    const searchCall = fetch.mock.calls.find((call) =>
      String(call[0]).includes("/api/search"),
    );
    expect(
      JSON.parse(String((searchCall?.[1] as RequestInit).body))
        .content_source_id,
    ).toBe(12);
  });

  it("scopes the search on the session tenant, not on the query string", async () => {
    const fetch = vi.fn(fetchFixture());

    await load(
      createLoadEvent({
        fetch,
        url: `${SEARCH_URL}?q=graph&learning_path_id=99`,
      }) as never,
    );

    const searchCall = fetch.mock.calls.find((call) =>
      String(call[0]).includes("/api/search"),
    );
    expect(
      JSON.parse(String((searchCall?.[1] as RequestInit).body))
        .learning_path_id,
    ).toBe(12);
  });

  it("reports a search that failed rather than showing it as no matches", async () => {
    const fetch = vi.fn(async (url: string | URL) =>
      String(url).includes("/api/search")
        ? new Response(null, { status: 500 })
        : fetchFixture()(url),
    );

    const data = (await load(
      createLoadEvent({ fetch, url: `${SEARCH_URL}?q=graph` }) as never,
    )) as SearchData;

    expect(data.results?.status).toBe("error");
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    await expect(
      load(
        createLoadEvent({
          authenticated: false,
          fetch: vi.fn(),
          url: SEARCH_URL,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/login", status: 303 });
  });
});

describe("search page", () => {
  it("puts the query in a GET form, so a search is a URL", () => {
    render(SearchPage, { data: pageData({}) });

    const form = screen
      .getByLabelText("Search your course material")
      .closest("form");
    expect(form?.getAttribute("method")).toBe("get");
    expect(screen.getByRole("button", { name: "Search" })).toBeTruthy();
  });

  it("renders the passages the server already found", () => {
    render(SearchPage, {
      data: pageData({
        query: "graph",
        results: { data: [result("Graphen")], status: "ready" },
      }),
    });

    expect(screen.getByText("Graphen")).toBeTruthy();
    expect(screen.getByText("Strong match")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain(
      "1 passages found",
    );
  });

  it("says a search found nothing, naming the query it answered", () => {
    render(SearchPage, {
      data: pageData({
        query: "nichts",
        results: { data: [], status: "ready" },
      }),
    });

    expect(screen.getByRole("status").textContent).toContain("nichts");
  });

  it("says the search failed rather than leaving the page silent", () => {
    render(SearchPage, {
      data: pageData({
        query: "graph",
        results: { data: [], status: "error" },
      }),
    });

    const announced = screen
      .getAllByRole("status")
      .map((node) => node.textContent)
      .join(" ");
    expect(announced).toContain("did not answer");
  });

  /**
   * A scope the learner does not have is not a service that failed. Telling
   * someone reading another tenant's course to "try again in a moment" sends
   * them at something that will never work.
   */
  it("says a refused scope is a scope, not an outage", () => {
    render(SearchPage, {
      data: pageData({
        query: "graph",
        results: { data: [], status: "unauthorized" },
      }),
    });

    const announced = screen
      .getAllByRole("status")
      .map((node) => node.textContent)
      .join(" ");
    expect(announced).toContain("outside what your account may read");
    expect(announced).not.toContain("did not answer");
  });

  it("offers the next action when there is nothing indexed to search", () => {
    render(SearchPage, {
      data: pageData({
        selectedSourceId: null,
        sources: { data: [], status: "ready" },
      }),
    });

    expect(screen.getByText("Nothing to search yet")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Add a content source" }),
    ).toBeTruthy();
  });

  /**
   * The criterion is explicit that live search is plain REST. A stream would
   * be invisible to the debounce and to the abort, so the page must not open
   * one at all.
   */
  it("opens no stream and no socket", () => {
    const eventSource = vi.fn();
    const webSocket = vi.fn();
    vi.stubGlobal("EventSource", eventSource);
    vi.stubGlobal("WebSocket", webSocket);

    try {
      render(SearchPage, {
        data: pageData({
          query: "graph",
          results: { data: [result("Graphen")], status: "ready" },
        }),
      });

      expect(eventSource).not.toHaveBeenCalled();
      expect(webSocket).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

type SearchData = {
  csrfToken: string | null;
  learningPathId: number | null;
  query: string;
  results: Panel<SearchResult[]> | null;
  selectedSourceId: number | null;
  sourceFilter: "all" | "document" | "transcript";
  sources: Panel<ContentSource[]>;
};

function pageData(overrides: Partial<SearchData>) {
  return {
    ...layoutData,
    csrfToken: "csrf-from-session",
    learningPathId: 12,
    query: "",
    results: null,
    selectedSourceId: 12,
    sourceFilter: "all" as const,
    sources: { data: [source()], status: "ready" } as Panel<ContentSource[]>,
    ...overrides,
  };
}

function source(): ContentSource {
  return {
    external_ref: "series-12",
    id: 12,
    title: "Algorithmen und Datenstrukturen",
  };
}

function result(title: string): SearchResult {
  return {
    chunk_text: "Ein Graph besteht aus Knoten und Kanten.",
    content_item_id: "item-1",
    end_time: 128,
    score: 0.82,
    source: "transcript",
    start_time: 65,
    title,
  };
}

/** Answers the way the endpoint does, including finding nothing for "nichts". */
function fetchFixture() {
  return async (url: string | URL, init?: RequestInit): Promise<Response> => {
    if (!String(url).includes("/api/search")) {
      return jsonResponse({ sources: [source()] });
    }
    const body = JSON.parse(String(init?.body ?? "{}")) as { query?: string };
    return jsonResponse({
      results: body.query === "nichts" ? [] : [searchResponseRow()],
    });
  };
}

function searchResponseRow() {
  return {
    chunk_text: "Ein Graph besteht aus Knoten und Kanten.",
    content_item_id: "item-1",
    end_time: 128,
    score: 0.82,
    source: "transcript",
    start_time: 65,
    title: "Graphen",
  };
}
