<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { m } from '$lib/paraglide/messages.js';
</script>

<PageHeader heading={m.study_heading()} summary={m.study_summary()} />

<section class="study-surface" aria-labelledby="study-card-heading">
  <div class="card-topline">
    <h2 id="study-card-heading">{m.study_card_prompt()}</h2>
    <span>{m.study_again_later()}</span>
  </div>

  <label for="recall-answer">{m.study_answer_label()}</label>
  <textarea id="recall-answer" rows="5"></textarea>

  <div class="study-actions" aria-label={m.study_heading()}>
    <button type="button">{m.study_reveal()}</button>
    <button type="button">{m.study_undo()}</button>
    <button type="button">{m.study_pause()}</button>
    <button type="button">{m.study_focus_mode()}</button>
  </div>

  <div class="grade-grid" aria-label="Grade">
    <button type="button" class="danger">{m.study_again()}</button>
    <button type="button">{m.study_hard()}</button>
    <button type="button">{m.study_good()}</button>
    <button type="button">{m.study_easy()}</button>
  </div>
</section>

<style>
  .study-surface {
    display: grid;
    max-width: 60rem;
    gap: 1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  .card-topline {
    display: grid;
    gap: 0.5rem;
  }

  h2 {
    margin: 0;
    font-size: 1.15rem;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  .card-topline span {
    color: var(--warning);
    font-weight: 700;
    overflow-wrap: anywhere;
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
  }

  .study-actions,
  .grade-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.6rem;
  }

  button {
    min-height: 2.75rem;
    min-width: 0;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem;
    overflow-wrap: anywhere;
  }

  .danger {
    border-color: var(--danger);
    color: var(--danger);
  }

  @media (max-width: 560px) {
    .study-actions,
    .grade-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>