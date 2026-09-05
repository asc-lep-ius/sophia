<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import type { Grade } from "$lib/study/session.svelte";

  type Props = {
    disabled?: boolean;
    onGrade: (grade: Grade) => void;
  };

  let { disabled = false, onGrade }: Props = $props();

  const grades = [
    { value: 1 as Grade, label: () => m.study_again(), tone: "again" },
    { value: 2 as Grade, label: () => m.study_hard(), tone: "hard" },
    { value: 3 as Grade, label: () => m.study_good(), tone: "good" },
    { value: 4 as Grade, label: () => m.study_easy(), tone: "easy" },
  ];
</script>

<!--
  A 2x2 grid rather than a row: on a phone this sits in the thumb zone, and
  every target stays past the 48px WCAG 2.2 minimum without the learner
  reaching across the screen. Tapping is the primary path; the number keys are
  the fast one.
-->
<fieldset class="grade-bar" {disabled}>
  <legend>{m.study_grade_legend()}</legend>
  <div class="grades">
    {#each grades as grade (grade.value)}
      <button
        type="button"
        class="grade"
        data-tone={grade.tone}
        data-grade={grade.value}
        aria-keyshortcuts={String(grade.value)}
        onclick={() => onGrade(grade.value)}
      >
        <span class="label">{grade.label()}</span>
        <kbd>{grade.value}</kbd>
      </button>
    {/each}
  </div>
</fieldset>

<style>
  .grade-bar {
    min-width: 0;
    margin: 0;
    border: 0;
    padding: 0;
  }

  legend {
    padding: 0 0 0.5rem;
    font-weight: 700;
  }

  .grades {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.6rem;
  }

  .grade {
    display: flex;
    min-height: 3.5rem;
    min-width: 3rem;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.75rem;
  }

  .grade[data-tone="again"] {
    border-color: var(--danger);
    color: var(--danger);
  }

  .grade[data-tone="easy"] {
    border-color: var(--accent-strong);
    color: var(--accent-strong);
  }

  .grade-bar[disabled] .grade {
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

  @media (min-width: 48rem) {
    .grades {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
  }
</style>
