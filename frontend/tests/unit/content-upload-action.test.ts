// @vitest-environment node
//
// The upload action is server code, and this suite hands it a real multipart
// request. Under jsdom the globals come from two realms — `Blob` from jsdom,
// `FormData` from undici — and a `File` built in one is refused by the other,
// which tests the environment rather than the action. Node is where it runs.
import type { Actions, RequestEvent } from "@sveltejs/kit";
import { describe, expect, it, vi } from "vitest";

import { actions } from "../../src/routes/content/sources/+page.server";

const TENANT_LEARNING_PATH = "12";
const PDF_BYTES = new Uint8Array([
  0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37,
]);

describe("content upload action", () => {
  it("accepts a multipart post and reports what the API queued", async () => {
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          byte_size: PDF_BYTES.byteLength,
          id: "upload-1",
          media_type: "application/pdf",
          state: "queued",
          title: "Graph algorithms",
        },
        201,
      ),
    );

    const result = await uploadAction(
      createEvent({
        fetch,
        form: uploadForm("Graph algorithms", "lecture-01.pdf"),
      }),
    );

    expect(result).toEqual({
      accepted: {
        byteSize: PDF_BYTES.byteLength,
        id: "upload-1",
        mediaType: "application/pdf",
        state: "queued",
        title: "Graph algorithms",
      },
    });
  });

  it("sends the file on as multipart, letting fetch set the boundary", async () => {
    // Reusing the browser's own Content-Type would describe a body that no
    // longer exists, so the action must not carry that header across.
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          byte_size: 8,
          id: "upload-1",
          media_type: "application/pdf",
          state: "queued",
          title: "Graph algorithms",
        },
        201,
      ),
    );

    await uploadAction(
      createEvent({
        fetch,
        form: uploadForm("Graph algorithms", "lecture-01.pdf"),
      }),
    );

    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/content-sources/uploads");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.headers as Headers).has("content-type")).toBe(false);
    expect((init.headers as Headers).get("x-csrf-token")).toBe(
      "csrf-from-session",
    );
  });

  it("refuses an unsupported file without spending a round trip on it", async () => {
    const fetch = vi.fn();

    const result = await uploadAction(
      createEvent({ fetch, form: uploadForm("Payload", "payload.exe") }),
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      data: { rejection: "unsupported_type", title: "Payload" },
      status: 422,
    });
  });

  it("refuses a submission with no title before uploading anything", async () => {
    const fetch = vi.fn();

    const result = await uploadAction(
      createEvent({ fetch, form: uploadForm("   ", "lecture-01.pdf") }),
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(result).toMatchObject({ data: { rejection: "title_required" } });
  });

  it("repeats the reason the API gave rather than a generic failure", async () => {
    // Only the server sees the bytes, so a renamed executable can only be
    // caught there; the form has to be able to say which check refused it.
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: "content.upload_rejected",
            params: { reason: "content_mismatch" },
          },
        },
        422,
      ),
    );

    const result = await uploadAction(
      createEvent({ fetch, form: uploadForm("Disguised", "lecture-01.pdf") }),
    );

    expect(result).toMatchObject({
      data: { rejection: "content_mismatch", title: "Disguised" },
      status: 422,
    });
  });

  it("keeps the title so a refusal does not cost the learner their typing", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 500 }));

    const result = await uploadAction(
      createEvent({
        fetch,
        form: uploadForm("Graph algorithms", "lecture-01.pdf"),
      }),
    );

    expect(result).toMatchObject({
      data: { rejection: "upload_failed", title: "Graph algorithms" },
      status: 502,
    });
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    const event = createEvent({
      authenticated: false,
      fetch: vi.fn(),
      form: uploadForm("Graph algorithms", "lecture-01.pdf"),
    });

    await expect(uploadAction(event)).rejects.toMatchObject({
      location: "/app/login",
      status: 303,
    });
  });
});

function uploadAction(event: RequestEvent) {
  const upload = (actions as Actions).upload;
  if (!upload) {
    throw new Error("the sources page has no upload action");
  }
  return upload(event);
}

function uploadForm(title: string, filename: string): FormData {
  const form = new FormData();
  form.set("title", title);
  form.set(
    "file",
    new File([PDF_BYTES], filename, { type: "application/pdf" }),
  );
  return form;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status,
  });
}

function createEvent({
  authenticated = true,
  fetch,
  form,
}: {
  authenticated?: boolean;
  fetch: ReturnType<typeof vi.fn>;
  form: FormData;
}): RequestEvent {
  const url = "http://localhost/app/content/sources";
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
      request_id: "req-upload",
      role: "student",
      sessionSettings: null,
      tenant: {
        learning_path_id: TENANT_LEARNING_PATH,
        org_id: "tu-wien",
        role: "student",
      },
      user: null,
    },
    request: new Request(url, { body: form, method: "POST" }),
    url: new URL(url),
  } as unknown as RequestEvent;
}
