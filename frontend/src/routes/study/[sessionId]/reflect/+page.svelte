<script lang="ts">
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import StudyCard from "$lib/components/study/StudyCard.svelte";
  import {
    completeSession,
    loadSessionSummary,
    saveReflection,
    type StudySessionSummary,
  } from "$lib/api/study";
  import { m } from "$lib/paraglide/messages.js";
  import { createStudyRuntime } from "$lib/study/runtime";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const anchorQuestion = $derived(data.questions.at(0));
  const context = $derived({
    csrfToken: data.csrfToken ?? "",
    learningPathId: data.learningPathId,
    sessionId: data.sessionId,
  });

  // Derived rather than built once: SvelteKit reuses this component across a
  // param change, and a runtime captured at init would outlive its session.
  const runtime = $derived(
    anchorQuestion
      ? createStudyRuntime({
          ...context,
          questions: [anchorQuestion],
          pacing: data.pacing,
          phase: "post_test",
        })
      : null,
  );

  let reflection = $state("");
  let elapsedSeconds = $state(0);
  let summary = $state<StudySessionSummary | null>(null);
  let submitting = $state(false);
  let failed = $state(false);

  const secondsLeft = $derived(
    Math.max(data.pacing.reflection_min_seconds - elapsedSeconds, 0),
  );
  const postTestDone = $derived(runtime === null || runtime.store.remaining === 0);
  const reflectionWritten = $derived(reflection.trim().length > 0);
  const canReveal = $derived(postTestDone && reflectionWritten && secondsLeft <= 0);

  $effect(() => {
    const current = runtime;
    current?.store.recordPromptShown();
    return () => current?.destroy();
  });

  // The countdown is the pedagogy, not a spinner: the floor comes from the
  // server (GET /api/study/pacing) so shortening it is a deployment change,
  // and the results stay closed until it elapses.
  $effect(() => {
    const ticker = setInterval(() => {
      elapsedSeconds += 1;
    }, 1000);
    return () => clearInterval(ticker);
  });

  async function revealResults() {
    if (!canReveal || submitting) {
      return;
    }
    submitting = true;
    failed = false;
    try {
      runtime?.events.record({
        eventType: "reflection_written",
        questionId: anchorQuestion?.id ?? null,
        payload: { text_length: reflection.trim().length },
      });
      await runtime?.events.flushNow();
      await saveReflection(context, {
        prompt: m.study_reflection_prompt(),
        reflectionText: reflection.trim(),
        requestId: crypto.randomUUID(),
      });
      await completeSession(context);
      summary = await loadSessionSummary(data.sessionId);
    } catch {
      failed = true;
    } finally {
      submitting = false;
    }
  }

  function percent(value: number | null | undefined): string {
    return value === null || value === undefined
      ? "—"
      : `${Math.round(value * 100)}%`;
  }

  function bandMessage(band: StudySessionSummary["band"]): string {
    switch (band) {
      case "well_calibrated":
        return m.study_band_well_calibrated();
      case "overconfident":
        return m.study_band_overconfident();
      case "underconfident":
        return m.study_band_underconfident();
      default:
        return m.study_band_unknown();
    }
  }
</script>

<PageHeader
  heading={m.study_reflect_heading()}
  summary={m.study_reflect_summary()}
/>

{#if runtime && !postTestDone}
  <section class="posttest" aria-labelledby="study-posttest-heading">
    <h2 id="study-posttest-heading">{m.study_posttest_heading()}</h2>
    <StudyCard
      store={runtime.store}
      hint={m.study_posttest_hint()}
      showQueue={false}
    />
  </section>
{/if}

{#if postTestDone && !summary}
  <section class="reflection" aria-labelledby="study-reflection-heading">
    <h2 id="study-reflection-heading">{m.study_reflection_label()}</h2>
    <p class="prompt">{m.study_reflection_prompt()}</p>
    <label class="sr-only" for="study-reflection">
      {m.study_reflection_label()}
    </label>
    <textarea
      id="study-reflection"
      rows="6"
      bind:value={reflection}
      aria-describedby="study-reflection-status"
    ></textarea>
    <p id="study-reflection-status" class="status" aria-live="polite">
      {#if secondsLeft > 0}
        {m.study_reflection_countdown({ seconds: secondsLeft })}
      {:else if !reflectionWritten}
        {m.study_reflection_required()}
      {/if}
    </p>
    <button type="button" disabled={!canReveal || submitting} onclick={() => void revealResults()}>
      {m.study_reflection_ready()}
    </button>
    {#if failed}
      <p class="error" role="alert">{m.study_not_available()}</p>
    {/if}
  </section>
{/if}

{#if summary}
  <section class="results" aria-labelledby="study-results-heading">
    <h2 id="study-results-heading">{m.study_results_heading()}</h2>
    <dl>
      <div>
        <dt>{m.study_predicted_label()}</dt>
        <dd data-testid="predicted">{percent(summary.predicted)}</dd>
      </div>
      <div>
        <dt>{m.study_measured_label()}</dt>
        <dd data-testid="measured">{percent(summary.measured)}</dd>
      </div>
      <div>
        <dt>{m.study_improvement_label()}</dt>
        <dd data-testid="improvement">
          {percent(summary.session.pre_test_score)} → {percent(
            summary.session.post_test_score,
          )}
        </dd>
      </div>
    </dl>
    <p class="band" data-band={summary.band}>{bandMessage(summary.band)}</p>
    {#if summary.legacy_scored}
      <p class="legacy">{m.study_legacy_scored()}</p>
    {/if}
    <a href={resolve("/study", {})}>{m.study_finish()}</a>
  </section>
{/if}

<style>
  .posttest,
  .reflection,
  .results {
    display: grid;
    max-width: 52rem;
    gap: 0.7rem;
    margin-bottom: 1rem;
  }

  .reflection,
  .results {
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
    overflow-wrap: anywhere;
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

  .prompt,
  .status,
  .band,
  .legacy,
  .error {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .status {
    min-height: 1.2rem;
    color: var(--muted);
    font-size: 0.9rem;
  }

  button,
  a {
    display: inline-flex;
    justify-self: start;
    min-height: 2.75rem;
    min-width: 3rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.9rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }

  button:disabled {
    opacity: 0.55;
  }

  dl {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
    margin: 0;
  }

  dl div {
    display: grid;
    min-width: 0;
    gap: 0.2rem;
  }

  dt {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  dd {
    margin: 0;
    font-size: 1.4rem;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .band[data-band="overconfident"] {
    color: var(--warning);
  }

  .legacy {
    color: var(--muted);
    font-size: 0.85rem;
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
