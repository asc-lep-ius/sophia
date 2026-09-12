export const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".epub",
  ".mp3",
  ".m4a",
  ".mp4",
  ".wav",
] as const;

/**
 * Mirrors `SOPHIA_CONTENT_UPLOAD_MAX_BYTES`, the proxy's `@api_uploads`
 * ceiling and the frontend container's `BODY_SIZE_LIMIT`. Kept here so the
 * form can name the limit before the learner spends a minute uploading past
 * it; the API is still what enforces it.
 */
export const MAX_UPLOAD_BYTES = 512 * 1024 * 1024;

export const UPLOAD_REJECTIONS = [
  "title_required",
  "title_too_long",
  "file_required",
  "empty_file",
  "too_large",
  "unsupported_type",
  "content_mismatch",
  "upload_failed",
] as const;

export type UploadRejection = (typeof UPLOAD_REJECTIONS)[number];

export type UploadSubmission = {
  file: File | null;
  title: string;
};

export type AcceptedUpload = {
  byteSize: number;
  id: string;
  mediaType: string;
  state: "queued" | "processing" | "failed" | "ready";
  title: string;
};

/**
 * The checks worth making before the bytes cross the network.
 *
 * Deliberately a subset of the API's: this cannot sniff the file's leading
 * bytes, so a renamed executable still has to be caught server-side. What it
 * does buy is refusing an obviously wrong pick without a 512 MB round trip.
 */
export function validateUpload(
  submission: UploadSubmission,
): UploadRejection | null {
  const title = submission.title.trim();
  if (title === "") {
    return "title_required";
  }
  if (title.length > 200) {
    return "title_too_long";
  }
  if (submission.file === null || submission.file.name === "") {
    return "file_required";
  }
  if (!hasAcceptedExtension(submission.file.name)) {
    return "unsupported_type";
  }
  if (submission.file.size === 0) {
    return "empty_file";
  }
  if (submission.file.size > MAX_UPLOAD_BYTES) {
    return "too_large";
  }
  return null;
}

export function hasAcceptedExtension(filename: string): boolean {
  const lowered = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((extension) => lowered.endsWith(extension));
}

/** The `accept` hint on the file input, from the one allowlist. */
export function acceptAttribute(): string {
  return ACCEPTED_EXTENSIONS.join(",");
}

/**
 * Read the API's own refusal, so the form repeats the reason it gave.
 *
 * Anything unrecognised collapses to `upload_failed` rather than being shown
 * raw: an error envelope is a machine contract, not a sentence for a learner.
 */
export function readRejection(body: unknown): UploadRejection {
  if (body === null || typeof body !== "object") {
    return "upload_failed";
  }
  const detail = (body as { detail?: unknown }).detail;
  if (detail === null || typeof detail !== "object") {
    return "upload_failed";
  }
  const params = (detail as { params?: unknown }).params;
  const reason =
    params !== null && typeof params === "object"
      ? (params as { reason?: unknown }).reason
      : null;
  return UPLOAD_REJECTIONS.includes(reason as UploadRejection)
    ? (reason as UploadRejection)
    : "upload_failed";
}

export function readAcceptedUpload(body: unknown): AcceptedUpload | null {
  if (body === null || typeof body !== "object") {
    return null;
  }
  const record = body as Record<string, unknown>;
  if (
    typeof record.id !== "string" ||
    typeof record.title !== "string" ||
    typeof record.media_type !== "string" ||
    typeof record.byte_size !== "number" ||
    !isIngestionState(record.state)
  ) {
    return null;
  }
  return {
    byteSize: record.byte_size,
    id: record.id,
    mediaType: record.media_type,
    state: record.state,
    title: record.title,
  };
}

function isIngestionState(value: unknown): value is AcceptedUpload["state"] {
  return (
    value === "queued" ||
    value === "processing" ||
    value === "failed" ||
    value === "ready"
  );
}
