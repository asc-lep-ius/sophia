import { describe, expect, it } from "vitest";

import {
  groupContent,
  isContentItemReady,
  type ContentItem,
  type ContentSource,
} from "../../src/lib/content/filters";

function item(overrides: Partial<ContentItem> = {}): ContentItem {
  return {
    download_status: "completed",
    id: "episode-1",
    index_status: "completed",
    missed_at: null,
    sequence_number: 1,
    skip_reason: null,
    title: "Vorlesung - VU vom 2026-01-16",
    transcription_status: "completed",
    ...overrides,
  };
}

const source: ContentSource = { external_ref: "", id: 7, title: "EP1" };

describe("content item readiness", () => {
  it("counts a lecture transcribed from the player's captions as ready", () => {
    // Captions need no download: the status row says "none" where a Whisper
    // lecture says "completed", and both are ready to study.
    const captioned = item({ download_status: "none", id: "episode-cc" });

    expect(isContentItemReady(captioned)).toBe(true);
    const groups = groupContent([source], new Map([[7, [captioned, item()]]]), {
      query: "",
      status: "ready",
    });
    expect(groups).toHaveLength(1);
    expect(groups[0]?.readyCount).toBe(2);
  });

  it("still waits for the transcript and the index", () => {
    expect(isContentItemReady(item({ transcription_status: "pending" }))).toBe(
      false,
    );
    expect(isContentItemReady(item({ index_status: "pending" }))).toBe(false);
  });
});
