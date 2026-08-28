# Study Surface Specification

The SvelteKit study surface starts as a scaffold in Phase 3. Later phases will connect it to the Athena review APIs without changing the interaction contract below.

## State Machine

1. `idle`: no card is loaded, or the queue is exhausted.
2. `loading`: the next card, review context, and pacing hints are being fetched.
3. `prompt`: the learner sees the card prompt and enters or rehearses an answer.
4. `revealed`: the expected answer, supporting references, and grading controls are visible.
5. `grading`: an optimistic grade is queued locally and sent to the API.
6. `committed`: the backend accepted the grade and the next card can load.
7. `rollback`: the optimistic grade failed, the local queue restores the card, and the error is announced.
8. `paused`: timers stop, shortcuts are ignored except resume, and the current card remains recoverable.

Invalid transitions are rejected. In particular, `prompt` cannot jump to `committed`, `rollback` must return to `revealed` or `prompt`, and `paused` resumes to the state that was active before pause.

## Keyboard and Pointer Bindings

- Reveal answer: `Space` or the reveal button.
- Grade again: `1` or the Again button.
- Grade hard: `2` or the Hard button.
- Grade good: `3` or the Good button.
- Grade easy: `4` or the Easy button.
- Undo last grade: `U` or the undo button.
- Pause or resume: `P` or the pause button.
- Focus mode: `F` or the focus mode toggle.
- Move between controls: standard `Tab` and `Shift+Tab`; no roving focus until the component needs composite widget semantics.

Shortcut handling must ignore editable text fields unless the shortcut includes an explicit modifier or the field documents the behavior.

## Required Indicators

- Again-later indicator: visible in `prompt`, `revealed`, and `grading`; updated optimistically with the outbox.
- Pause state: persistent visual state plus `aria-live` announcement when timers pause or resume.
- Focus mode: hides secondary panels, never hides the current card, answer field, or primary grading controls.
- Undo availability: disabled when no grade is in the reversible history window.

## Optimistic Grade Outbox

The client may move immediately from `revealed` to the next `prompt` after a grade, but it must keep an outbox entry with card id, selected grade, previous queue position, and request id. If the API accepts, the entry is removed. If the API rejects or times out beyond the retry boundary, the queue rolls back, the card is restored, and the user receives a non-blocking error with a retry action.

Undo first checks the outbox. If the grade is still pending, cancel it locally. If it is already committed and the backend supports reversal, send a compensating undo request. If reversal is not possible, explain that the grade has already been saved.

## Pacing and Latency Boundaries

- Prompt to reveal is learner-controlled; no auto-reveal.
- Optimistic grade feedback should appear within 100 ms of input.
- API round trips for grade commit should target under 250 ms p50 on local deployment and remain non-blocking up to the retry boundary.
- Pacing hints should avoid shame language. They can suggest pauses, interleaving, or again-later scheduling based on confidence and latency.
- The surface must preserve answer text across transient network failures and page-level retry attempts.