import { render, screen } from "@testing-library/svelte";
import type { RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import ProcessingPanel from "../../src/lib/components/content/ProcessingPanel.svelte";
import TopicsPage from "../../src/routes/topics/+page.svelte";
import { actions } from "../../src/routes/content/sources/+page.server";
import {
  isJobActive,
  itemOutcome,
  readIngestionStatus,
  readRefusalReason,
  type IngestionJob,
  type IngestionSourceStatus,
  type IngestionStatus,
} from "../../src/lib/content/ingestion";
import type { ContentItem, TopicRow } from "../../src/lib/content/filters";
import type { Panel } from "../../src/lib/dashboard/panels";

const LEARNING_PATH = 82774;
const { process, settings } = actions as Required<typeof actions>;

describe("processing panel", () => {
  it("offers Process and says nothing has run yet", () => {
    render(ProcessingPanel, panelProps({}));

    const button = screen.getByRole("button", { name: "Process" });
    expect(button.closest("form")?.getAttribute("action")).toBe("?/process");
    expect(screen.getByRole("status").textContent).toContain(
      "Not processed yet",
    );
  });

  it("shows the running stage and keeps Process from being pressed again", () => {
    render(
      ProcessingPanel,
      panelProps({
        status: readyStatus({
          job: job({ state: "processing", stage: "transcribe" }),
        }),
      }),
    );

    expect(screen.getByRole("status").textContent).toContain("transcribing");
    const button = screen.getByRole("button", {
      name: "Process",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("refuses visibly when no worker can process, with the worker's reason", () => {
    render(
      ProcessingPanel,
      panelProps({
        status: readyStatus({
          worker: {
            available: false,
            reason: "No usable NVIDIA GPU: nvidia-smi found none",
            gpu_name: "",
          },
        }),
      }),
    );

    expect(screen.getByRole("alert").textContent).toContain(
      "No usable NVIDIA GPU: nvidia-smi found none",
    );
    const button = screen.getByRole("button", {
      name: "Process",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("says when processing is already running", () => {
    render(
      ProcessingPanel,
      panelProps({
        processResult: { outcome: "already_running", reason: "" },
      }),
    );

    expect(screen.getByRole("alert").textContent).toContain("already running");
  });

  it("names a failed lecture's reason and shows the rest as ready", () => {
    render(
      ProcessingPanel,
      panelProps({
        sources: [
          {
            id: 3022060,
            title: "EP1",
            items: [
              item({ id: "ok", title: "Schleifen", sequence_number: 1 }),
              item({
                id: "bad",
                title: "Arrays",
                sequence_number: 2,
                index_status: "failed",
                topic_status: null,
                failure_reason: "no kernel image is available",
              }),
            ],
          },
        ],
      }),
    );

    const rows = screen
      .getAllByRole("listitem")
      .map((row) => row.textContent ?? "");
    expect(rows[0]).toContain("Lecture 1:");
    expect(rows[0]).toContain("Topics ready");
    expect(rows[1]).toContain("Failed: no kernel image is available");
  });

  it("offers to stop following a followed course, and to follow one that is not", () => {
    const followed = render(
      ProcessingPanel,
      panelProps({
        status: readyStatus({
          settings: {
            learning_path_id: LEARNING_PATH,
            subscribed: true,
            transcription_language: "en",
          },
        }),
      }),
    );
    expect(screen.getByRole("button", { name: "Stop following" })).toBeTruthy();
    const language = screen.getByLabelText(
      "Transcription language",
    ) as HTMLSelectElement;
    expect(language.value).toBe("en");
    followed.unmount();

    render(ProcessingPanel, panelProps({}));
    expect(
      screen.getByRole("button", { name: "Follow new recordings" }),
    ).toBeTruthy();
    const detect = screen.getByLabelText(
      "Transcription language",
    ) as HTMLSelectElement;
    expect(detect.value).toBe("");
  });
});

describe("process action", () => {
  it("reports the API's refusals as outcomes with their reason", async () => {
    const unavailable = await process(
      event(
        new Response(
          JSON.stringify({
            detail: {
              code: "ingestion.unavailable",
              params: { reason: "No processing worker is running" },
            },
          }),
          { status: 503 },
        ),
      ) as never,
    );
    const running = await process(
      event(new Response(null, { status: 409 })) as never,
    );
    const started = await process(
      event(new Response("{}", { status: 202 })) as never,
    );

    expect(unavailable).toEqual({
      process: {
        outcome: "unavailable",
        reason: "No processing worker is running",
      },
    });
    expect(running).toEqual({
      process: { outcome: "already_running", reason: "" },
    });
    expect(started).toEqual({ process: { outcome: "started", reason: "" } });
  });

  it("posts the settings form as the API's JSON body", async () => {
    const fetch = vi.fn(async () => new Response("{}", { status: 200 }));
    const form = new FormData();
    form.set("subscribed", "false");
    form.set("transcription_language", "de");

    const result = await settings(event(fetch, form) as never);

    expect(result).toEqual({ settingsSaved: true });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain(
      `/learning-paths/${LEARNING_PATH}/ingestion/settings`,
    );
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({
      subscribed: false,
      transcription_language: "de",
    });
  });
});

describe("ingestion helpers", () => {
  it("reads only a body that is the contract", () => {
    expect(readIngestionStatus(readyStatus({}))).not.toBeNull();
    expect(readIngestionStatus({ learning_path_id: 1 })).toBeNull();
    expect(readIngestionStatus(null)).toBeNull();
  });

  it("knows which jobs are still worth polling for", () => {
    expect(isJobActive(null)).toBe(false);
    expect(isJobActive(job({ state: "queued" }))).toBe(true);
    expect(isJobActive(job({ state: "processing" }))).toBe(true);
    expect(isJobActive(job({ state: "ready" }))).toBe(false);
    expect(isJobActive(job({ state: "failed" }))).toBe(false);
  });

  it("calls an item ready only once its topics are extracted", () => {
    expect(itemOutcome(item({}))).toBe("ready");
    expect(itemOutcome(item({ topic_status: null }))).toBe("pending");
    expect(
      itemOutcome(
        item({ transcription_status: "processing", topic_status: null }),
      ),
    ).toBe("processing");
    expect(itemOutcome(item({ download_status: "failed" }))).toBe("failed");
  });

  it("reads the reason out of the error envelope and nothing else", () => {
    expect(
      readRefusalReason({ detail: { code: "x", params: { reason: "r" } } }),
    ).toBe("r");
    expect(readRefusalReason({ detail: { code: "x", params: {} } })).toBe("");
    expect(readRefusalReason("nope")).toBe("");
  });
});

describe("topics page", () => {
  it("names the lecture each topic came from", () => {
    render(TopicsPage, {
      data: {
        authenticated: true,
        contentLanguage: {
          language: "de",
          origin: "learning_path",
          override: null,
        },
        drawerOpen: false,
        filters: { origin: "all", query: "", rated: "all" },
        learningPathId: LEARNING_PATH,
        locale: "en",
        rows: {
          status: "ready",
          data: [
            {
              confidence: null,
              topic: {
                topic: "Rekursive Methoden",
                learning_path_id: LEARNING_PATH,
                source: "transcript",
                frequency: 2,
                content_items: [
                  { id: "ep-3", title: "Methoden", sequence_number: 3 },
                  { id: "ep-x", title: "Wiederholung", sequence_number: null },
                ],
              },
            },
          ],
        } as Panel<TopicRow[]>,
        settings: null,
        tenant: {
          learning_path_id: String(LEARNING_PATH),
          org_id: "tu-wien",
          role: "student",
        },
        theme: "light",
        totalCount: 1,
        uiLocale: "en",
        user: null,
      } as never,
    });

    const texts = screen
      .getAllByRole("listitem")
      .map((node) => node.textContent?.trim() ?? "");
    expect(
      texts.some((text) => text.includes("From lecture 3: Methoden")),
    ).toBe(true);
    expect(texts.some((text) => text.includes("From Wiederholung"))).toBe(true);
  });
});

function readyStatus(overrides: Partial<IngestionStatus>): IngestionStatus {
  return {
    learning_path_id: LEARNING_PATH,
    settings: {
      learning_path_id: LEARNING_PATH,
      subscribed: false,
      transcription_language: null,
    },
    worker: {
      available: true,
      reason: "",
      gpu_name: "NVIDIA GeForce GTX 1070",
    },
    job: null,
    sources: [{ id: 3022060, title: "EP1" }],
    ...overrides,
  };
}

function job(overrides: Partial<IngestionJob>): IngestionJob {
  return {
    id: 7,
    learning_path_id: LEARNING_PATH,
    state: "queued",
    requested_by: "student",
    stage: null,
    content_source_id: null,
    error: null,
    requested_at: "2026-10-10T06:00:00+00:00",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function item(overrides: Partial<ContentItem>): ContentItem {
  return {
    id: "ep-1",
    title: "Lecture",
    download_status: "none",
    skip_reason: null,
    transcription_status: "completed",
    index_status: "completed",
    sequence_number: null,
    missed_at: null,
    topic_status: "completed",
    failure_reason: null,
    ...overrides,
  };
}

function panelProps(overrides: {
  status?: IngestionStatus;
  sources?: IngestionSourceStatus[];
  processResult?: {
    outcome: "started" | "already_running" | "unavailable";
    reason: string;
  };
}) {
  return {
    learningPathId: LEARNING_PATH,
    status: {
      status: "ready",
      data: overrides.status ?? readyStatus({}),
    } as Panel<IngestionStatus | null>,
    sources: overrides.sources ?? [],
    processResult: overrides.processResult ?? null,
    processFailed: false,
    settingsSaved: false,
    settingsFailed: false,
  };
}

function event(
  responseOrFetch: Response | ((...args: unknown[]) => Promise<Response>),
  form: FormData = new FormData(),
): Partial<RequestEvent> {
  const fetch =
    typeof responseOrFetch === "function"
      ? responseOrFetch
      : vi.fn(async () => responseOrFetch);
  return {
    cookies: {
      get: () => undefined,
      getAll: () => [],
      set: () => undefined,
      delete: () => undefined,
      serialize: () => "",
    },
    fetch: fetch as never,
    locals: {
      authenticated: true,
      locale: "en",
      settings: null,
      tenant: {
        learning_path_id: String(LEARNING_PATH),
        org_id: "tu-wien",
        role: "student",
      },
      theme: "light",
      user: null,
    } as never,
    request: new Request("http://localhost/app/content/sources?/process", {
      method: "POST",
      body: form,
    }),
    url: new URL("http://localhost/app/content/sources"),
  };
}
