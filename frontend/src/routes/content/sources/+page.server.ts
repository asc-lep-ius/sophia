import { fail, redirect, type Actions, type RequestEvent } from "@sveltejs/kit";
import { apiFetch } from "../../../hooks.server";
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
import type { PageServerLoad } from "./$types";

type ApiEvent = Parameters<typeof apiFetch>[0];

export const load: PageServerLoad = async (event) => {
  requireAuthenticated(event);

  const override = readLanguageOverride(event.url);
  const learningPathId = numericLearningPathId(
    event.locals.tenant.learning_path_id,
  );
  const [sources, contentLanguage] = await Promise.all([
    loadSources(event),
    loadContentLanguage(event, learningPathId, override),
  ]);

  return { contentLanguage, sources, uiLocale: event.locals.locale };
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

function numericLearningPathId(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
