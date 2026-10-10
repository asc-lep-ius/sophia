// @vitest-environment node
//
// The upload form may only promise processing while something consumes the
// staging directory. Nothing does until #133 wires uploads into the pipeline,
// so this test fails if a locale says an upload is queued, transcribed or
// indexed while no backend module reads what `stage_upload` writes.
//
// When #133 adds that reader this guard goes quiet on its own; that issue is
// also what restores the processing copy (see content_upload_state_stored).
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND = join(import.meta.dirname, "..", "..");
const BACKEND = join(FRONTEND, "..", "src", "sophia");
const MESSAGES = join(FRONTEND, "messages");
const WRITER_MODULE = join("services", "content_uploads.py");

/** What a reader of the staging directory has to touch. */
const STAGING_READ = /\b(staging_dir|STAGING_DIR_NAME|stored_path)\b/;

/** Promises of processing, in the locales the app ships. */
const PROCESSING_PROMISE =
  /queue|transcri|index|in the background|warteschlange|eingereiht|transkri|indiz|im hintergrund/i;

function pythonFiles(dir: string): string[] {
  return readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".py"))
    .map((entry) => join(entry.parentPath, entry.name));
}

function stagingConsumers(): string[] {
  return pythonFiles(BACKEND)
    .map((file) => relative(BACKEND, file))
    .filter((file) => file !== WRITER_MODULE)
    .filter((file) =>
      STAGING_READ.test(readFileSync(join(BACKEND, file), "utf8")),
    );
}

function uploadMessages(): [string, string, string][] {
  return readdirSync(MESSAGES)
    .filter((file) => file.endsWith(".json"))
    .flatMap((file) => {
      const messages = JSON.parse(
        readFileSync(join(MESSAGES, file), "utf8"),
      ) as Record<string, unknown>;
      return Object.entries(messages)
        .filter(([key]) => key.startsWith("content_upload_"))
        .map(([key, text]): [string, string, string] => [
          file,
          key,
          String(text),
        ]);
    });
}

describe("upload copy matches what happens to an upload", () => {
  it("finds the upload messages in every locale", () => {
    const locales = new Set(uploadMessages().map(([file]) => file));
    expect([...locales].sort()).toEqual(["de.json", "en.json"]);
  });

  it("promises no processing while nothing reads the staging directory", () => {
    if (stagingConsumers().length > 0) return;

    const promised = uploadMessages().filter(([, , text]) =>
      PROCESSING_PROMISE.test(text),
    );
    // A promise in a locale file is a promise to every learner who reads it.
    expect(promised.map(([file, key]) => `${file}:${key}`)).toEqual([]);
  });
});
