# Frontend Form Writes Decision

Status: accepted 2026-09-12

## Context

Issue #100 proposes building the content-management writes "using Superforms
and Zod", and says to "use the exact Superforms/Zod pins from Phase 1 unless
implementation-day research requires a lockfile-reviewed patch update".

There are no such pins. Neither package appears in `frontend/package.json`,
`frontend/pnpm-lock.yaml`, `frontend/scripts/assert-package-contract.mjs` or
anywhere else on the branch. Phase 1 never added them, so following the
instruction literally would mean choosing two new runtime dependencies and
their versions here, which is not what "use the exact pins" asks for.

Three things about the surrounding code bear on the choice:

- Every write already on the SvelteKit surface — login, settings, quickstart's
  two save steps, study's session start and deck extension, review's grade — is
  a SvelteKit form action that validates the submitted `FormData` on the server
  and answers with `fail(status, …)`. There is one established pattern, used
  six times.
- The client bundle sits under a size-limit gate. Before this phase it measured
  87.9 kB gzipped against a 95 kB budget whose own note says it was set "with
  room for roughly one more surface". This phase adds three.
- The acceptance criteria in #100 name no library. They ask that the upload
  work without JavaScript, that topic filters be usable on a phone, and that
  content language default from the course rather than the UI locale.

## Decision

Build the #100 writes with SvelteKit form actions and hand-written server-side
validation, matching the six writes already on the surface. Do not add
`sveltekit-superforms` or `zod`.

What Superforms is for — server-side validation with progressive enhancement
and per-field messages surfaced back to the form — is what a form action plus
`fail()` already does here, and what the `?/upload` action does in this phase.
The part a schema library would genuinely add is declarative field-level
errors, which the upload form does not need: its refusals are one reason at a
time, and the authoritative one comes from the API rather than from the
browser's side of the wire.

The validation itself is deliberately split:

- `frontend/src/lib/content/upload.ts` holds the pre-check the form action runs
  before spending a round trip — title present, extension on the allowlist,
  non-empty, under the ceiling.
- `src/sophia/services/content_uploads.py` holds the decision. Only the server
  sees the bytes, so only the server can catch a renamed executable, and the
  action repeats whichever reason the API gives.

Restating that allowlist in a Zod schema would have added a third place for it
to drift, not removed one.

## Known constraint: the upload is buffered twice

The no-JavaScript path costs memory that the enhanced path would not.

A browser posts the multipart body to `?/upload` on the SvelteKit container,
which calls `event.request.formData()` and rebuilds the file as a `FormData`
before forwarding it to the API. Undici materialises file parts in memory, so
one upload at the 512 MB ceiling allocates roughly 512 MB of frontend-container
heap, and a handful of concurrent uploads will exhaust it. The API hop is not
affected — Starlette spools a file part to disk — but the frontend hop is, and
this phase is what exposed it: before `BODY_SIZE_LIMIT` was raised to match the
proxy, adapter-node refused anything over its 512 kB default.

This is written down rather than fixed because both available fixes are larger
than they look:

- **Stream the body through** instead of rebuilding it. That is the right
  answer and removes the buffer entirely, but a SvelteKit form action does not
  hand you the raw stream once `formData()` has been awaited, and reaching past
  it means parsing multipart in the action.
- **Lower the ceiling.** Cheap, but it is a product decision — how large a
  lecture recording a learner may upload — and it would make the three hops
  disagree, which `test_upload_ceilings_agree_across_proxy_frontend_and_api`
  exists to prevent.

Until one of those lands, treat the frontend container's memory limit as the
real concurrency cap on uploads, and size it accordingly. A per-tenant upload
quota, which the staging directory also wants, is the other half of this.

## Consequences

- No new runtime dependency, and no second form pattern for a reviewer to hold
  in their head alongside the first.
- Field-level validation messages, if a later surface needs them, are an open
  question rather than a settled one. A form with many independently invalid
  fields is the case that would justify revisiting this; nothing in #100 has
  one.
- The size budget still moved, to 108 kB — but on route code and message keys,
  not on a library. `frontend/package.json` records the measured split.

## Guardrails

- `frontend/tests/unit/content-upload-action.test.ts` covers the action's
  accept path, its local refusals, and that it repeats the API's reason rather
  than a generic failure.
- `frontend/tests/unit/content-sources-page.test.ts` covers the form carrying
  `method="post"` and `enctype="multipart/form-data"` with no client-only step
  between the learner and the action.
- `frontend/tests/e2e/content-topics.spec.ts` runs the upload with JavaScript
  switched off, which is the criterion this decision has to keep true.
- `tests/unit/test_content_uploads.py` and `tests/api/test_content_sources.py`
  cover the server-side checks that are the authoritative half.
