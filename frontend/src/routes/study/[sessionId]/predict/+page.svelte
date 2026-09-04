<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import StudyCard from "$lib/components/study/StudyCard.svelte";
  import { recordPrediction } from "$lib/api/study";
  import { m } from "$lib/paraglide/messages.js";
  import { createStudyRuntime } from "$lib/study/runtime";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const RATINGS = [
    { value: 1, label: () => m.study_predict_1() },
    { value: 2, label: () => m.study_predict_2() },
    { value: 3, label: () => m.study_predict_3() },
    { value: 4, label: () => m.study_predict_4() },
    { value: 5, label: () => m.study_predict_5() },
  ];

  // Derived rather than built once: SvelteKit reuses this component across a
  // param change, and a runtime captured at init would outlive its session.
  const anchorQuestion = $derived(data.questions.at(0));
  const runtime = $derived(
    anchorQuestion
      ? createStudyRuntime({
          csrfToken: data.csrfToken ?? "",
          learningPathId: data.learningPathId,
          sessionId: data.sessionId,
          questions: [anchorQuestion],
          pacing: data.pacing,
          phase: "pre_test",
        })
      : null,
  );

  let rating = $state<number | null>(null);
  let predictionSaved = $state(false);
  let predictionError = $state(false);

  const preTestDone = $derived(runtime !== null && runtime.store.remaining === 0);
  const canContinue = $derived(predictionSaved && preTestDone);

  $effect(() => {
    const current = runtime;
    current?.store.recordPromptShown();
    return () => current?.destroy();
  });

  async function choose(value: number) {
    rating = value;
    predictionError = false;
    runtime?.events.record({
      eventType: "prediction_made",
      questionId: anchorQuestion?.id ?? null,
      payload: { rating: value },
    });

    try {
      await recordPrediction(
        {
          csrfToken: data.csrfToken ?? "",
          learningPathId: data.learningPathId,
          sessionId: data.sessionId,
        },
        {
          topic: data.summary.session.topic,
          rating: value,
          requestId: crypto.randomUUID(),
        },
      );
      predictionSaved = true;
    } catch {
      predictionSaved = false;
      predictionError = true;
    }
  }

  async function continueToStudy() {
    if (!canContinue) {
      return;
    }
    await runtime?.events.flushNow().catch(() => undefined);
    await goto(
      resolve("/study/[sessionId]/act", { sessionId: String(data.sessionId) }),
    );
  }
</script>

<PageHeader
  heading={m.study_predict_heading()}
  summary={m.study_predict_summary()}
/>

<section class="prediction" aria-labelledby="study-prediction-legend">
  <fieldset>
    <legend id="study-prediction-legend">
      {m.study_predict_legend({ topic: data.summary.session.topic })}
    </legend>
    <div class="ratings">
      {#each RATINGS as option (option.value)}
        <label class="rating" class:selected={rating === option.value}>
          <input
            type="radio"
            name="prediction"
            value={option.value}
            checked={rating === option.value}
            onchange={() => void choose(option.value)}
          />
          <span>{option.label()}</span>
        </label>
      {/each}
    </div>
  </fieldset>
  {#if predictionError}
    <p class="error" role="alert">{m.study_not_available()}</p>
  {/if}
</section>

<section class="pretest" aria-labelledby="study-pretest-heading">
  <h2 id="study-pretest-heading">{m.study_pretest_heading()}</h2>
  {#if runtime && !preTestDone}
    <StudyCard
      store={runtime.store}
      hint={m.study_pretest_hint()}
      showQueue={false}
    />
  {:else if runtime}
    <p class="done" role="status">{m.study_finished()}</p>
  {:else}
    <p class="error">{m.study_queue_empty()}</p>
  {/if}
</section>

<div class="advance">
  <button type="button" disabled={!canContinue} onclick={() => void continueToStudy()}>
    {m.study_predict_continue()}
  </button>
  {#if !canContinue}
    <p class="requirement">{m.study_predict_required()}</p>
  {/if}
</div>

<style>
  .prediction,
  .pretest {
    display: grid;
    max-width: 52rem;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  fieldset {
    min-width: 0;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 0.9rem;
  }

  legend {
    padding: 0 0.35rem;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .ratings {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
    gap: 0.5rem;
  }

  .rating {
    display: flex;
    min-height: 3rem;
    min-width: 0;
    align-items: center;
    gap: 0.5rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    padding: 0.55rem 0.7rem;
    overflow-wrap: anywhere;
  }

  .rating.selected {
    border-color: var(--accent-strong);
    color: var(--accent-strong);
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
    overflow-wrap: anywhere;
  }

  .advance {
    display: grid;
    max-width: 52rem;
    gap: 0.4rem;
  }

  button {
    justify-self: start;
    min-height: 2.75rem;
    min-width: 3rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.9rem;
    overflow-wrap: anywhere;
  }

  button:disabled {
    opacity: 0.55;
  }

  .requirement,
  .error,
  .done {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .requirement,
  .done {
    color: var(--muted);
    font-size: 0.9rem;
  }

  .error {
    color: var(--danger);
  }
</style>
