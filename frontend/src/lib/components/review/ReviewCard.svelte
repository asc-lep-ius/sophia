<script lang="ts">
  import { browser } from "$app/environment";
  import AnswerField from "$lib/components/study/card/AnswerField.svelte";
  import GradeBar from "$lib/components/study/GradeBar.svelte";
  import KeyboardHelp from "$lib/components/study/KeyboardHelp.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import { isEditableTarget, resolveShortcut } from "$lib/study/keyboard";
  import type { Grade } from "$lib/study/session.svelte";
  import type { ReviewQueueStore } from "$lib/review/queue.svelte";

  type Props = {
    store: ReviewQueueStore;
  };

  let { store }: Props = $props();

  const RECALL_FIELD_ID = "review-recall";
  const CLOCK_INTERVAL_MS = 250;

  let helpOpen = $state(false);

  const current = $derived(store.current);

  // Moving to the next topic must not drop focus on the document body: the
  // keyboard learner would land back at the top of the page on every grade.
  $effect(() => {
    const position = store.position;
    if (!browser || position === 0) {
      return;
    }
    document.getElementById(RECALL_FIELD_ID)?.focus();
  });

  // Revealing removes the button that was focused; without this the learner is
  // dropped on the body at the moment the grades appear.
  $effect(() => {
    if (!browser || !store.current?.revealed) {
      return;
    }
    document.querySelector<HTMLButtonElement>('[data-grade="1"]')?.focus();
  });

  // Nothing else changes while the dwell floor runs down, so the store needs a
  // clock of its own for the reveal to become available.
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
        store.grade(shortcut.rating as Grade);
        return;
      case "undo":
        store.undo();
        return;
      case "help":
        helpOpen = true;
        return;
      default:
        // Pause and focus mode belong to a session with a clock behind it;
        // review has neither, and inventing them here would be two more
        // behaviours to keep in step with the study surface.
        return;
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if current}
  <section class="review-card" aria-labelledby="review-card-topic">
    <div class="queue">
      <span>{m.review_position({ position: store.position, total: store.total })}</span>
      {#if store.pendingCount > 0}
        <span class="pending">{m.study_pending_grades({ count: store.pendingCount })}</span>
      {/if}
      {#if store.failedCount > 0}
        <span class="unsaved">{m.study_unsaved_grades({ count: store.failedCount })}</span>
      {/if}
    </div>

    <h2 id="review-card-topic">{current.topic}</h2>
    <p class="prompt">{m.review_prompt()}</p>

    <AnswerField
      id={RECALL_FIELD_ID}
      disabled={false}
      hint={m.review_recall_hint()}
      minChars={store.minRecallChars}
      onInput={(value) => store.setRecall(value)}
      value={store.recall}
    />

    {#if !current.revealed}
      <button
        type="button"
        class="reveal"
        disabled={!store.canReveal}
        aria-keyshortcuts="Space"
        onclick={() => store.reveal()}
      >
        {m.review_reveal()}
      </button>
      <p class="sr-only" role="status">
        {store.canReveal ? m.study_reveal_available() : ""}
      </p>
    {:else}
      <div class="revealed">
        <h3>{m.study_your_answer()}</h3>
        <p class="own-answer">{current.recall}</p>
      </div>
      <!-- The same grade bar the study surface uses: one Again/Hard/Good/Easy
           scale, one set of thumb-zone targets, one set of shortcuts. -->
      <GradeBar onGrade={(grade) => store.grade(grade)} />
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
      <button type="button" aria-keyshortcuts="?" onclick={() => (helpOpen = true)}>
        {m.study_keyboard_help()}
      </button>
    </div>
  </section>
{/if}

{#if store.error}
  <div class="error" role="alert">
    <p>{m.review_grade_rejected()}</p>
    <button type="button" onclick={() => store.dismissError()}>{m.study_dismiss()}</button>
  </div>
{/if}

<!-- Outside the error banner: dismissing a message must not remove the only
     way to send a rejected review. -->
{#if store.failedCount > 0}
  <div
    class="unsent"
    role="group"
    aria-label={m.study_unsaved_grades({ count: store.failedCount })}
  >
    {#each store.outboxEntries.filter((entry) => entry.status === "failed") as entry (entry.requestId)}
      <!--
        Disabled rather than silently ignored once the send ceiling is reached:
        a control that looks live and does nothing teaches the learner to press
        it harder, and every press here is another write to an endpoint that
        cannot fold duplicates.
      -->
      <button
        type="button"
        disabled={!store.canRetry(entry.requestId)}
        onclick={() => void store.retryFailed(entry.requestId)}
      >
        {m.review_retry_topic({ topic: entry.payload.topic })}
      </button>
    {/each}
  </div>
{/if}

<KeyboardHelp open={helpOpen} onClose={() => (helpOpen = false)} />

<style>
  .review-card {
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

  .unsaved {
    color: var(--danger);
    font-weight: 700;
  }

  h2 {
    margin: 0;
    font-size: clamp(1.1rem, 1rem + 0.6vw, 1.4rem);
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  h3 {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
  }

  .queue span,
  .prompt,
  .own-answer {
    overflow-wrap: anywhere;
  }

  .prompt,
  .own-answer {
    margin: 0;
  }

  .prompt {
    color: var(--muted);
  }

  .own-answer {
    white-space: pre-wrap;
  }

  .revealed {
    display: grid;
    gap: 0.3rem;
    border-left: 3px solid var(--accent-strong);
    padding-left: 0.75rem;
  }

  .controls,
  .unsent {
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

  .error {
    display: grid;
    max-width: 52rem;
    justify-items: start;
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

  .unsent {
    max-width: 52rem;
    margin-top: 0.5rem;
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
</style>
