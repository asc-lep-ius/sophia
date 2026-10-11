<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import { CONFIDENCE_KEYS } from "$lib/study/keyboard";
  import type { Confidence } from "$lib/study/session.svelte";

  type Props = {
    disabled?: boolean;
    onChoose: (confidence: Confidence) => void;
  };

  let { disabled = false, onChoose }: Props = $props();

  const levels = [
    { value: 1, key: CONFIDENCE_KEYS[0], label: () => m.study_confidence_1() },
    { value: 2, key: CONFIDENCE_KEYS[1], label: () => m.study_confidence_2() },
    { value: 3, key: CONFIDENCE_KEYS[2], label: () => m.study_confidence_3() },
    { value: 4, key: CONFIDENCE_KEYS[3], label: () => m.study_confidence_4() },
    { value: 5, key: CONFIDENCE_KEYS[4], label: () => m.study_confidence_5() },
  ] satisfies { value: Confidence; key: string; label: () => string }[];
</script>

<!--
  Asked between the answer and the reveal, and only there: choosing a level is
  what reveals the card, so the judgement is committed before the material can
  colour it.
-->
<fieldset class="confidence-bar" {disabled} aria-describedby="study-confidence-note">
  <legend>{m.study_confidence_legend()}</legend>
  <p id="study-confidence-note" class="note">{m.study_confidence_note()}</p>
  <div class="levels">
    {#each levels as level (level.value)}
      <button
        type="button"
        class="level"
        data-confidence={level.value}
        aria-keyshortcuts={level.key.toUpperCase()}
        onclick={() => onChoose(level.value)}
      >
        <span class="label">{level.label()}</span>
        <kbd>{level.key.toUpperCase()}</kbd>
      </button>
    {/each}
  </div>
</fieldset>

<style>
  .confidence-bar {
    min-width: 0;
    margin: 0;
    border: 0;
    padding: 0;
  }

  legend {
    padding: 0 0 0.25rem;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .note {
    margin: 0 0 0.5rem;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .levels {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr));
    gap: 0.5rem;
  }

  .level {
    display: flex;
    min-height: 3rem;
    min-width: 3rem;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.6rem 0.75rem;
  }

  .confidence-bar[disabled] .level {
    opacity: 0.55;
  }

  .label {
    overflow-wrap: anywhere;
  }

  kbd {
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--muted);
    padding: 0.05rem 0.35rem;
    font-size: 0.75rem;
  }
</style>
