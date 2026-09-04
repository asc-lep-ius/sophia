<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";

  type Props = {
    id?: string;
    value: string;
    disabled?: boolean;
    minChars: number;
    hint?: string;
    onInput: (value: string) => void;
  };

  let {
    id = "study-answer",
    value,
    disabled = false,
    minChars,
    hint,
    onInput,
  }: Props = $props();

  const remaining = $derived(Math.max(minChars - value.trim().length, 0));
  const descriptionId = $derived(`${id}-description`);
</script>

<div class="answer-field">
  <label for={id}>{m.study_answer_label()}</label>
  {#if hint}
    <p class="hint">{hint}</p>
  {/if}
  <textarea
    {id}
    {disabled}
    rows="5"
    aria-describedby={descriptionId}
    value={value}
    oninput={(event) => onInput(event.currentTarget.value)}
  ></textarea>
  <!--
    Polite, not assertive: this updates on every keystroke, and an assertive
    region would interrupt a screen-reader user mid-word.
  -->
  <p id={descriptionId} class="counter" aria-live="polite">
    {remaining > 0 ? m.study_reveal_blocked({ remaining }) : ""}
  </p>
</div>

<style>
  .answer-field {
    display: grid;
    min-width: 0;
    gap: 0.35rem;
  }

  label {
    font-weight: 700;
  }

  textarea {
    width: 100%;
    min-width: 0;
    resize: vertical;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.75rem;
    font: inherit;
  }

  .hint,
  .counter {
    margin: 0;
    min-height: 1.2rem;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }
</style>
