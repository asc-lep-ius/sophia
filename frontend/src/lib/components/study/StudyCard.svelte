<script lang="ts">
  import AnswerField from "./card/AnswerField.svelte";
  import CardPrompt from "./card/CardPrompt.svelte";
  import GradeBar from "./GradeBar.svelte";
  import KeyboardHelp from "./KeyboardHelp.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import { isEditableTarget, resolveShortcut } from "$lib/study/keyboard";
  import { browser } from "$app/environment";
  import type { Grade, StudySessionStore } from "$lib/study/session.svelte";

  type Props = {
    store: StudySessionStore;
    hint?: string;
    showQueue?: boolean;
  };

  let { store, hint, showQueue = true }: Props = $props();

  const ANSWER_FIELD_ID = "study-answer";
  const CLOCK_INTERVAL_MS = 250;

  let helpOpen = $state(false);
  let answerValue = $derived(store.answer);

  const current = $derived(store.current);
  const canReveal = $derived(store.canReveal);

  // Moving to the next card must not drop focus on the body: the keyboard
  // learner would land back at the top of the document on every grade.
  $effect(() => {
    const position = store.position;
    if (!browser || position === 0 || store.paused) {
      return;
    }
    document.getElementById(ANSWER_FIELD_ID)?.focus();
  });

  // Revealing removes the button that was focused. Without this the keyboard
  // learner is dropped on the document body at the exact moment the grades
  // appear — WCAG 2.4.3, and the difference between a fast flow and a hunt.
  $effect(() => {
    if (!browser || !store.current?.revealed || store.paused) {
      return;
    }
    document.querySelector<HTMLButtonElement>('[data-grade="1"]')?.focus();
  });

  // Nothing else on the page changes while the dwell floor runs down, so the
  // store needs a clock of its own for the reveal to become available.
  $effect(() => {
    if (!browser) {
      return;
    }
    const clock = setInterval(() => store.tick(), CLOCK_INTERVAL_MS);
    return () => clearInterval(clock);
  });

  function handleKeydown(event: KeyboardEvent) {
    const shortcut = resolveShortcut(event, {
      editing: isEditableTarget(event.target),
    });
    if (!shortcut) {
      return;
    }

    event.preventDefault();
    switch (shortcut.action) {
      case "reveal":
        store.reveal();
        return;
      case "grade":
        void store.grade(shortcut.rating as Grade);
        return;
      case "undo":
        store.undo();
        return;
      case "pause":
        store.togglePause();
        return;
      case "focus":
        store.toggleFocusMode();
        return;
      case "help":
        helpOpen = true;
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if current}
  <section
    class="study-card"
    class:focus-mode={store.focusMode}
    aria-labelledby="study-card-prompt"
  >
    {#if showQueue && !store.focusMode}
      <div class="queue" aria-live="polite">
        <span>
          {m.study_card_position({
            position: store.position,
            total: store.total,
          })}
        </span>
        <span class="again-later">
          {m.study_again_later({ count: store.againLaterCount })}
        </span>
        {#if store.pendingCount > 0}
          <span class="pending">
            {m.study_pending_grades({ count: store.pendingCount })}
          </span>
        {/if}
      </div>
    {/if}

    <CardPrompt question={current.question} />

    <AnswerField
      id={ANSWER_FIELD_ID}
      value={answerValue}
      disabled={store.paused}
      minChars={store.minElaborationChars}
      {hint}
      onInput={(value) => store.setAnswer(value)}
    />

    {#if store.paused}
      <p class="paused" role="status">{m.study_paused_notice()}</p>
    {/if}

    {#if !current.revealed}
      <button
        type="button"
        class="reveal"
        disabled={!canReveal || store.paused}
        aria-keyshortcuts="Space"
        onclick={() => store.reveal()}
      >
        {m.study_reveal()}
      </button>
      {#if !canReveal && store.elaborationChars >= store.minElaborationChars}
        <p class="dwell" role="status">{m.study_dwell_blocked()}</p>
      {/if}
      <!--
        Announced once, when the state actually changes: the character counter
        is described-by rather than live for the same reason.
      -->
      <p class="sr-only" role="status">
        {canReveal ? m.study_reveal_available() : ""}
      </p>
    {:else}
      <div class="revealed">
        <h3>{m.study_your_answer()}</h3>
        <p class="own-answer">{current.answer}</p>
      </div>
      <GradeBar
        disabled={store.paused}
        onGrade={(grade) => void store.grade(grade)}
      />
    {/if}

    <div class="controls">
      <button
        type="button"
        disabled={!store.canUndo}
        aria-keyshortcuts="U"
        onclick={() => store.undo()}
      >
        {m.study_undo()}
      </button>
      <button type="button" aria-keyshortcuts="P" onclick={() => store.togglePause()}>
        {store.paused ? m.study_resume() : m.study_pause()}
      </button>
      <button
        type="button"
        aria-keyshortcuts="F"
        aria-pressed={store.focusMode}
        onclick={() => store.toggleFocusMode()}
      >
        {store.focusMode ? m.study_focus_mode_on() : m.study_focus_mode()}
      </button>
      <button type="button" aria-keyshortcuts="?" onclick={() => (helpOpen = true)}>
        {m.study_keyboard_help()}
      </button>
    </div>
  </section>
{/if}

{#if store.error}
  <div class="error" role="alert">
    <p>
      {store.error === "study.undo_already_committed"
        ? m.study_undo_already_committed()
        : m.study_grade_rejected()}
    </p>
    <div class="error-actions">
      {#each store.outboxEntries.filter((entry) => entry.status === "failed") as entry (entry.requestId)}
        <button type="button" onclick={() => void store.retryFailed(entry.requestId)}>
          {m.study_retry()}
        </button>
      {/each}
      <button type="button" onclick={() => store.dismissError()}>
        {m.study_dismiss()}
      </button>
    </div>
  </div>
{/if}

<KeyboardHelp open={helpOpen} onClose={() => (helpOpen = false)} />

<style>
  .study-card {
    display: grid;
    max-width: 52rem;
    min-width: 0;
    gap: 0.85rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  .queue {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.75rem;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .again-later {
    color: var(--warning);
    font-weight: 700;
  }

  .queue span,
  .paused,
  .dwell,
  .own-answer,
  h3 {
    overflow-wrap: anywhere;
  }

  h3 {
    margin: 0;
    font-size: 0.9rem;
    color: var(--muted);
  }

  .revealed {
    display: grid;
    gap: 0.3rem;
    border-left: 3px solid var(--accent-strong);
    padding-left: 0.75rem;
  }

  .own-answer,
  .paused,
  .dwell {
    margin: 0;
    white-space: pre-wrap;
  }

  .controls {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  button {
    min-height: 2.75rem;
    min-width: 3rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.8rem;
    overflow-wrap: anywhere;
  }

  button:disabled {
    opacity: 0.55;
  }

  .reveal {
    justify-self: start;
  }

  /*
    Focus mode retracts the chrome around the card, never the card itself:
    the prompt, the answer field and the grades stay put so nothing the
    learner is working on can disappear under a keystroke.
  */
  .focus-mode .controls {
    opacity: 0.6;
  }

  .focus-mode:focus-within .controls {
    opacity: 1;
  }

  .error {
    display: grid;
    max-width: 52rem;
    gap: 0.5rem;
    margin-top: 0.75rem;
    border: 1px solid var(--danger);
    border-radius: 8px;
    padding: 0.75rem;
  }

  .error p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .error-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
</style>
