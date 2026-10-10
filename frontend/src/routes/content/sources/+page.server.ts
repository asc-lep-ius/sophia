import { fail, redirect, type Actions, type RequestEvent } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
import { selectedLearningPathId } from "$lib/learningPath";
import {
  panelFromResponse,
  unavailablePanel,
  type Panel,
} from "$lib/dashboard/panels";
import type { ContentSource } from "$lib/content/filters";
import {
  fallbackContentLanguage,
  readContentLanguage,
  readLanguageOverride,
  type ContentLanguageState,
} from "$lib/content/language";
import {
  readAcceptedUpload,
  readRejection,
  validateUpload,
  type UploadRejection,
} from "$lib/content/upload";
import {
  readIngestionStatus,
  readRefusalReason,
  TRANSCRIPTION_LANGUAGES,
  type IngestionSourceStatus,
  type IngestionStatus,
  type ProcessOutcome,
} from "$lib/content/ingestion";
import type { ContentItem } from "$lib/content/filters";
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export const load: PageServerLoad = async (event) => {
  requireAuthenticated(event);

  const override = readLanguageOverride(event.url);
  const learningPathId = selectedLearningPathId(event.locals.tenant);
  const [sources, contentLanguage, ingestion] = await Promise.all([
    loadSources(event),
    loadContentLanguage(event, learningPathId, override),
    loadIngestion(event, learningPathId),
  ]);
  const ingestionSources = await loadIngestionSources(event, ingestion.data);

  return {
    contentLanguage,
    ingestion,
    ingestionSources,
    learningPathId,
    sources,
    uiLocale: event.locals.locale,
  };
};

export const actions: Actions = {
  /**
   * The base upload path, reachable by a plain multipart form post.
   *
   * No `use:enhance` is required to get here: the browser posts the form, this
   * runs, and the page re-renders with either the accepted upload or the
   * reason it was refused. The enhanced client adds progress and cancellation
   * on top of this, never instead of it.
   */
  upload: async (event) => {
    requireAuthenticated(event);

    const formData = await event.request.formData();
    const title = readFormString(formData, "title");
    const file = formData.get("file");
    const submission = {
      file: file instanceof File ? file : null,
      title,
    };

    // A local pre-check so an obviously wrong pick does not cost a round trip.
    // It is not the decision: only the API sees the bytes, and only the bytes
    // can say whether a file is what its name claims.
    const local = validateUpload(submission);
    if (local !== null) {
      return uploadFailure(422, local, title);
    }

    return forwardUpload(event, submission.file as File, title);
  },

  /**
   * Re-scan the connected systems for sources.
   *
   * Kept on this page rather than on the catalog: #100 makes the setup surface
   * the one place a content source arrives from, whether it is discovered or
   * uploaded, so an ingestion adapter added later has a home already.
   */
  /**
   * Press Process: queue the selected course for the worker.
   *
   * The two refusals the API makes on purpose — already running, and no
   * worker that can process here — come back as outcomes the page says,
   * with the reason the API attached. Everything else is a failure.
   */
  process: async (event) => {
    requireAuthenticated(event);
    const learningPathId = selectedLearningPathId(event.locals.tenant);
    if (learningPathId === null) {
      return fail(403, { processFailed: true });
    }

    let response: Response;
    try {
      response = await apiFetch(
        event,
        "/api/learning-paths/{learning_path_id}/ingestion",
        { method: "POST", params: { learning_path_id: learningPathId } },
      );
    } catch {
      return fail(502, { processFailed: true });
    }
    if (response.status === 401) {
      redirect(303, "/app/login");
    }
    if (response.status === 409) {
      return { process: processOutcome("already_running", "") };
    }
    if (response.status === 503) {
      const reason = readRefusalReason(await safeJson(response));
      return { process: processOutcome("unavailable", reason) };
    }
    if (!response.ok) {
      return fail(safeFailureStatus(response.status), { processFailed: true });
    }
    return { process: processOutcome("started", "") };
  },

  /** Stop or resume following the course, and set its transcription language. */
  settings: async (event) => {
    requireAuthenticated(event);
    const learningPathId = selectedLearningPathId(event.locals.tenant);
    if (learningPathId === null) {
      return fail(403, { settingsFailed: true });
    }
    const formData = await event.request.formData();
    const language = readFormString(formData, "transcription_language");
    if (!TRANSCRIPTION_LANGUAGES.includes(language as never)) {
      return fail(422, { settingsFailed: true });
    }
    const body = {
      subscribed: readFormString(formData, "subscribed") === "true",
      transcription_language: language === "" ? null : language,
    };

    let response: Response;
    try {
      response = await apiFetch(
        event,
        "/api/learning-paths/{learning_path_id}/ingestion/settings",
        {
          method: "PUT",
          params: { learning_path_id: learningPathId },
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        },
      );
    } catch {
      return fail(502, { settingsFailed: true });
    }
    if (response.status === 401) {
      redirect(303, "/app/login");
    }
    if (!response.ok) {
      return fail(safeFailureStatus(response.status), { settingsFailed: true });
    }
    return { settingsSaved: true };
  },

  discover: async (event) => {
    requireAuthenticated(event);

    try {
      const response = await apiFetch(event, "/api/content-sources/discover", {
        method: "POST",
      });
      if (response.status === 401) {
        redirect(303, "/app/login");
      }
      if (!response.ok) {
        return fail(safeFailureStatus(response.status), {
          discoverFailed: true,
        });
      }
      return { discovered: true };
    } catch {
      return fail(502, { discoverFailed: true });
    }
  },
};

async function forwardUpload(event: RequestEvent, file: File, title: string) {
  // Rebuilt rather than streamed through: the incoming multipart boundary
  // belongs to the browser's request, and reusing it would send the API a body
  // whose header no longer describes it.
  const body = new FormData();
  body.set("title", title);
  body.set("file", file, file.name);

  let response: Response;
  try {
    response = await apiFetch(event, "/api/content-sources/uploads", {
      body,
      method: "POST",
    });
  } catch {
    return uploadFailure(502, "upload_failed", title);
  }

  if (response.status === 401) {
    redirect(303, "/app/login");
  }
  if (!response.ok) {
    return uploadFailure(
      safeFailureStatus(response.status),
      readRejection(await safeJson(response)),
      title,
    );
  }

  const accepted = readAcceptedUpload(await safeJson(response));
  if (accepted === null) {
    return uploadFailure(502, "upload_failed", title);
  }
  return { accepted };
}

function uploadFailure(
  status: 400 | 401 | 403 | 422 | 502,
  rejection: UploadRejection,
  title: string,
) {
  // The title comes back so the learner does not retype it after a refusal;
  // the file cannot, because a browser will not let a value be put back into a
  // file input, and keeping the bytes server-side to replay them would be a
  // cache nobody asked for.
  return fail(status, { rejection, title });
}

function processOutcome(outcome: ProcessOutcome, reason: string) {
  return { outcome, reason };
}

async function loadIngestion(
  event: ApiEvent,
  learningPathId: number | null,
): Promise<Panel<IngestionStatus | null>> {
  if (learningPathId === null) {
    return { status: "ready", data: null };
  }
  try {
    const response = await apiFetch(
      event,
      "/api/learning-paths/{learning_path_id}/ingestion",
      { params: { learning_path_id: learningPathId } },
    );
    return await panelFromResponse(response, readIngestionStatus, null);
  } catch {
    return unavailablePanel(null);
  }
}

/**
 * The state of every recording the course owns, one request per source.
 *
 * Read from the ingestion-status route rather than kept client-side, so a
 * reload or a tab opened later shows what the worker has actually done.
 */
async function loadIngestionSources(
  event: ApiEvent,
  status: IngestionStatus | null,
): Promise<IngestionSourceStatus[]> {
  if (status === null) {
    return [];
  }
  return Promise.all(
    status.sources.map(async (source) => {
      try {
        const response = await apiFetch(
          event,
          "/api/content-sources/{content_source_id}/ingestion-status",
          { params: { content_source_id: source.id } },
        );
        // 404 is a source with no registered recordings yet, not a failure.
        const items = response.ok
          ? (readItemList(await safeJson(response)) ?? [])
          : [];
        return { id: source.id, title: source.title, items };
      } catch {
        return { id: source.id, title: source.title, items: [] };
      }
    }),
  );
}

function readItemList(body: unknown): ContentItem[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const items = (body as Record<string, unknown>).items;
  if (!Array.isArray(items)) {
    return null;
  }
  return items.every(
    (item) =>
      item !== null &&
      typeof item === "object" &&
      typeof (item as ContentItem).id === "string" &&
      typeof (item as ContentItem).title === "string",
  )
    ? (items as ContentItem[])
    : null;
}

async function loadSources(event: ApiEvent): Promise<Panel<ContentSource[]>> {
  try {
    const response = await apiFetch(event, "/api/content-sources");
    return await panelFromResponse(response, readSourceList, []);
  } catch {
    return unavailablePanel([]);
  }
}

async function loadContentLanguage(
  event: ApiEvent,
  learningPathId: number | null,
  override: ReturnType<typeof readLanguageOverride>,
): Promise<ContentLanguageState> {
  if (learningPathId === null) {
    return fallbackContentLanguage(override);
  }

  try {
    const response = await apiFetch(
      event,
      "/api/learning-paths/{learning_path_id}/content-language",
      {
        params: { learning_path_id: learningPathId },
        query: { lang: override },
      },
    );
    if (!response.ok) {
      return fallbackContentLanguage(override);
    }
    return (
      readContentLanguage(await response.json(), override) ??
      fallbackContentLanguage(override)
    );
  } catch {
    return fallbackContentLanguage(override);
  }
}

function requireAuthenticated(event: RequestEvent): void {
  if (!event.locals.authenticated) {
    redirect(303, "/app/login");
  }
}

function readSourceList(body: unknown): ContentSource[] | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const sources = (body as Record<string, unknown>).sources;
  if (!Array.isArray(sources)) {
    return null;
  }
  return sources.every(
    (source) =>
      source !== null &&
      typeof source === "object" &&
      typeof (source as ContentSource).id === "number" &&
      typeof (source as ContentSource).title === "string",
  )
    ? (sources as ContentSource[])
    : null;
}

function readFormString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function safeFailureStatus(status: number): 400 | 401 | 403 | 422 | 502 {
  if (status === 401 || status === 403 || status === 422) {
    return status;
  }
  if (status >= 400 && status < 500) {
    return 400;
  }
  return 502;
}
