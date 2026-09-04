# Study Surface Specification

The SvelteKit study surface implements the Equilibration Cycle: predict, act,
reflect. It is the surface at `/app/study`; the NiceGUI page it replaces stays
reachable at `/legacy/study` until phase 5 removes it, but nothing links there.

Where this document and issue #98 disagreed, the issue won and this document
was corrected: an earlier draft described a reveal-and-grade loop in which a
learner could "rehearse" an answer rather than produce one, and left scoring to
the client. Both are now wrong by construction.

## Route Shape

| Route | Phase | What the learner does |
|---|---|---|
| `/app/study` | — | Start a session, or resume one |
| `/app/study/{id}/predict` | `pre_test` | Commit a confidence prediction, then answer the anchor question |
| `/app/study/{id}/act` | `practice` | Work the remaining cards |
| `/app/study/{id}/reflect` | `post_test` | Answer the anchor question again, reflect, then see the numbers |

The session's first generated question is its **anchor**: answered before
studying and again afterwards. That is what makes the pre→post figure a
comparison rather than two unrelated numbers.

## State Machine

1. `idle`: no card is loaded, or the queue is exhausted.
2. `loading`: the next card, review context, and pacing hints are being fetched.
3. `prompt`: the learner sees the card prompt and writes their own answer.
4. `revealed`: the learner's answer, its provenance, and the grading controls
   are visible. There is no expected answer to reveal — nothing in the system
   stores an answer key — so the reveal opens self-assessment, and the score
   comes from the learner's own Again/Hard/Good/Easy rating.
5. `grading`: an optimistic grade is queued locally and sent to the API.
6. `committed`: the backend accepted the grade and the next card can load.
7. `rollback`: the optimistic grade failed, the local queue restores the card, and the error is announced.
8. `paused`: timers stop, shortcuts are ignored except resume, and the current card remains recoverable.

Invalid transitions are rejected. In particular, `prompt` cannot jump to
`committed` (a grade before a reveal is refused), `rollback` returns to
`revealed`, and `paused` resumes to the state that was active before pause with
the dwell clock restarted — a pause is not engagement.

## Productive Friction

These are requirements, not defaults. `frontend/tests/e2e/study-pacing.spec.ts`
fails when any of them is shortened.

- **Elaboration floor.** Reveal stays disabled until the learner has written at
  least the question's `min_elaboration_chars`. The floor travels with the
  question because the server evaluates that same policy on submission.
- **Prompt dwell floor.** Reveal also waits for `min_prompt_dwell_ms` with the
  prompt on screen.
- **Un-skippable pre-test.** The predict route will not advance until both a
  confidence prediction and a pre-test answer are recorded.
- **Reflection pause.** The results stay closed for
  `reflection_min_seconds` — served by `GET /api/study/pacing`, not compiled
  into the client — and until a reflection is written.

The server enforces the first two independently: an attempt whose ingested
learner-process trace does not satisfy the policy is refused with 412. The
client's copy of the floors is there to explain what is missing, not to be
trusted.

## Keyboard and Pointer Bindings

- Reveal answer: `Space` or the reveal button.
- Grade again / hard / good / easy: `1`–`4` or the grade buttons.
- Undo last grade: `U` or the undo button.
- Pause or resume: `P` or the pause button.
- Focus mode: `F` or the focus mode toggle.
- Shortcut help: `?` or the shortcuts button.
- Move between controls: standard `Tab` and `Shift+Tab`.

Shortcuts are inert while focus is in an editable field, so typing an answer
can never grade a card; a learner reaches them by tabbing out. Every shortcut
has a visible control, and the help dialog lists them.

Focus follows the work: the answer field takes focus with each new card, and
the grade controls take it when the reveal removes the button that had it.

## Required Indicators

- Again-later indicator: visible in `prompt`, `revealed`, and `grading`; updated optimistically with the outbox.
- Unsent-grade count: visible whenever the outbox holds anything.
- Pause state: persistent visual state plus `aria-live` announcement when timers pause or resume.
- Focus mode: retracts secondary chrome, never the current card, answer field, or grading controls.
- Undo availability: disabled when no grade is in the reversible history window.
- Provenance: every card says whether a model or the learner wrote it.

## Optimistic Grade Outbox

The client may move immediately from `revealed` to the next `prompt` after a
grade, but it must keep an outbox entry with card id, selected grade, previous
queue position, and request id. If the API accepts, the entry is removed. A
failure the server would repeat (4xx other than 429) rolls back at once; a
transient one is retried with the same request id — which is what makes the
retry idempotent server-side — before rolling back. On rollback the card is
restored at its queue position and the learner gets a non-blocking error with a
retry action.

Undo first checks the outbox. If the grade is still pending, cancel it locally.
If it has already been accepted, say so: the grade is durable, and showing a
queue the server does not have would be a lie.

## Scores

The client never computes a score, and never infers one from whether an answer
is non-empty. Grades are the learner's self-rating, sent as given. Pre-test and
post-test scores are the server's means over the session's phased attempts,
returned by `completeStudySession`. Predicted-against-measured, the calibration
delta, and the calibration band come from `getStudySessionSummary`. The surface
localizes the band's wording; it does not decide it.

## Realtime

`GET /api/study/{id}/events` is a same-origin `EventSource`: native EventSource
cannot set headers, so the stream authenticates with the session cookie while
mutating POSTs keep the CSRF header. Events are notifications — durable state
is what the submission endpoints returned — so a dropped event costs a refresh
at worst, never a lost grade. The stream reconnects on its own with
`Last-Event-ID`; a `gap` event says the replay window was missed.

## Pacing and Latency Boundaries

- Prompt to reveal is learner-controlled; no auto-reveal.
- Next, reveal, and focus navigation have a 50 ms p95 interaction budget,
  measured from the browser's own `event` timing entries under 4x CPU
  throttling against a fixed fixture deck
  (`frontend/tests/e2e/study-latency.spec.ts`). Persistence and stream
  acknowledgement complete asynchronously through the outbox and are outside
  that budget.
- Optimistic grade feedback should appear within 100 ms of input.
- API round trips for grade commit should target under 250 ms p50 on local
  deployment and remain non-blocking up to the retry boundary.
- Pacing hints avoid shame language. They can suggest pauses, interleaving, or
  again-later scheduling based on confidence and latency.
- The surface must preserve answer text across transient network failures and
  page-level retry attempts.

## Touch

Grade controls sit in a thumb-zone 2x2 grid at 48 CSS pixels or larger. Tap is
the primary action for every control; a swipe may only ever shortcut something
a tap already does (WCAG 2.2 dragging movements). Haptics and gestures are
progressive enhancements.
