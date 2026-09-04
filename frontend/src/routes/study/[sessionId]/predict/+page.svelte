<script lang="ts">
  import { enhance } from "$app/forms";
  import { goto } from "$app/navigation";
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import StudyCard from "$lib/components/study/StudyCard.svelte";
  import { recordPrediction } from "$lib/api/study";
  import { m } from "$lib/paraglide/messages.js";
  import { anchorCard, remainingCards } from "$lib/study/deck";
  import { createStudyRuntime } from "$lib/study/runtime";
  import type { ActionData, PageData } from "./$types";

  type Props = { data: PageData; form: ActionData };

  let { data, form }: Props = $props();

  const RATINGS = [
    { value: 1, label: () => m.study_predict_1() },
    { value: 2, label: () => m.study_predict_2() },
    { value: 3, label: () => m.study_predict_3() },
    { value: 4, label: () => m.study_predict_4() },
    { value: 5, label: () => m.study_predict_5() },
  ];

  const anchorQuestion = $derived(anchorCard(data.questions));
  // Already answered on a previous visit: the pre-test is done, and asking
  // again would write a second attempt into the pre-test mean.
  const preTestAnswered = $derived(
    anchorQuestion !== undefined &&
      data.attemptedQuestionIds.includes(anchorQuestion.id),
  );

  // Rebuilt when the session changes, or when its deck grows — and not when
  // some unrelated `invalidateAll` hands the page a fresh data object, which
  // would discard the answer a learner is part-way through writing.
  const runtime = $derived.by(() => {
    // The one tracked read: rebuilding on anything else would throw away a
    // card in progress.
    void `${data.sessionId}:${data.questions.length}:${data.attemptedQuestionIds.length}`;
    return untrack(() => {
      const question = remainingCards(
        anchorCard(data.questions) ? [anchorCard(data.questions)!] : [],
        data.attemptedQuestionIds,
      ).at(0);
      return question
        ? createStudyRuntime({
            csrfToken: data.csrfToken ?? "",
            learningPathId: data.learningPathId,
            sessionId: data.sessionId,
            questions: [question],
            pacing: data.pacing,
            phase: "pre_test",
          })
        : null;
    });
  });

  let rating = $state<number | null>(null);
  let predictionSaved = $state(false);
  let predictionError = $state(false);

  const preTestDone = $derived(
    preTestAnswered || (runtime !== null && runtime.store.remaining === 0),
  );
  // The pre-test grade is held for a moment like any other, but unlike any
  // other card this one is not re-presented if it never lands: the flow has
  // moved past predict. So Continue waits for the outbox to be empty rather
  // than for the optimistic advance.
  const preTestSettled = $derived(
    runtime === null ||
      (runtime.store.pendingCount === 0 && runtime.store.failedCount === 0),
  );
  const canContinue = $derived(predictionSaved && preTestDone && preTestSettled);

  $effect(() => {
    const current = runtime;
    current?.store.recordPromptShown();
    return () => current?.destroy();
  });

  // `$effect` cleanup does not run when the tab closes or the page is hard
  // reloaded, which is exactly when a held grade would be lost. `pagehide`
  // fires in both, and on mobile it is the only one that reliably does.
  $effect(() => {
    const current = runtime;
    const flush = () => current?.flushOnUnload();
    // pageshow undoes it: pagehide also fires into the bfcache, and a restored
    // page goes on being used.
    const resume = () => current?.resumeFromUnload();
    window.addEventListener("pagehide", flush);
    window.addEventListener("pageshow", resume);
    return () => {
      window.removeEventListener("pagehide", flush);
      window.removeEventListener("pageshow", resume);
    };
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
  <!--
    A resumed session whose pre-test is already answered is finished, not
    broken: the empty-deck error below is for a session that has no cards at
    all, which is a state a learner can act on.
  -->
  {#if preTestDone}
    <p class="done" role="status">{m.study_finished()}</p>
  {:else if runtime}
    <StudyCard
      store={runtime.store}
      hint={m.study_pretest_hint()}
      showQueue={false}
    />
  {:else}
    <div class="empty-deck">
      <p class="error">{m.study_queue_empty()}</p>
      <form method="POST" action="?/generate" use:enhance>
        <input type="hidden" name="topic" value={data.summary.session.topic} />
        <button type="submit">{m.study_extend()}</button>
      </form>
      {#if form?.error}
        <p class="error" role="alert">{m.study_extend_failed()}</p>
      {/if}
    </div>
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

  .empty-deck {
    display: grid;
    gap: 0.5rem;
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
