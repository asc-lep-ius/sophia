import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import SourcesPage from "../../src/routes/content/sources/+page.svelte";
import type { ContentSource } from "../../src/lib/content/filters";
import type { ContentLanguageState } from "../../src/lib/content/language";
import type { Panel } from "../../src/lib/dashboard/panels";

const TENANT_LEARNING_PATH = "12";

describe("content sources page", () => {
  it("posts multipart to the action with nothing client-only in the way", () => {
    render(SourcesPage, { data: pageData({}), form: null });

    const form = screen
      .getByRole("button", { name: "Upload" })
      .closest("form") as HTMLFormElement;

    expect(form.getAttribute("method")?.toLowerCase()).toBe("post");
    expect(form.getAttribute("enctype")).toBe("multipart/form-data");
    expect(form.getAttribute("action")).toBe("?/upload");
    expect(screen.getByLabelText("Title")).toBeTruthy();
    expect(screen.getByLabelText("File")).toBeTruthy();
  });

  it("names the accepted formats on the input as well as in the hint", () => {
    render(SourcesPage, { data: pageData({}), form: null });

    const file = screen.getByLabelText("File") as HTMLInputElement;
    expect(file.getAttribute("accept")).toBe(".pdf,.epub,.mp3,.m4a,.mp4,.wav");
    expect(screen.getByText(/Accepted: \.pdf,\.epub/)).toBeTruthy();
  });

  it("shows the refusal as an alert and puts the title back", () => {
    render(SourcesPage, {
      data: pageData({}),
      form: { rejection: "too_large", title: "Graph algorithms" },
    });

    expect(screen.getByRole("alert").textContent).toContain("512 MB limit");
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
      "Graph algorithms",
    );
  });

  it("points a refusal at the field it is about", () => {
    render(SourcesPage, {
      data: pageData({}),
      form: { rejection: "unsupported_type", title: "Payload" },
    });

    const file = screen.getByLabelText("File");
    expect(file.getAttribute("aria-invalid")).toBe("true");
    expect(file.getAttribute("aria-describedby")).toContain("upload-error");
    // The title was fine, so it must not be marked as the problem.
    expect(
      screen.getByLabelText("Title").getAttribute("aria-invalid"),
    ).toBeNull();
  });

  it("blames no field when the upload failed for neither", () => {
    render(SourcesPage, {
      data: pageData({}),
      form: { rejection: "upload_failed", title: "Graph algorithms" },
    });

    expect(
      screen.getByLabelText("File").getAttribute("aria-invalid"),
    ).toBeNull();
    expect(
      screen.getByLabelText("Title").getAttribute("aria-invalid"),
    ).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("says an accepted upload is queued rather than finished", () => {
    render(SourcesPage, {
      data: pageData({}),
      form: {
        accepted: {
          byteSize: 8,
          id: "upload-1",
          mediaType: "application/pdf",
          state: "queued",
          title: "Graph algorithms",
        },
      },
    });

    expect(screen.getByRole("status").textContent).toContain(
      "Graph algorithms",
    );
    expect(screen.getByText(/queued for transcription/)).toBeTruthy();
  });
});

type SourcesData = {
  contentLanguage: ContentLanguageState;
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

function pageData(overrides: Partial<SourcesData>) {
  return {
    ...layoutData,
    contentLanguage: {
      language: "de",
      origin: "learning_path",
      override: null,
    } satisfies ContentLanguageState,
    sources: { data: [], status: "ready" } as Panel<ContentSource[]>,
    uiLocale: "en" as const,
    ...overrides,
  };
}
