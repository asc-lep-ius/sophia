<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { untrack } from "svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import StudyCard from "$lib/components/study/StudyCard.svelte";
  import { SophiaApiError } from "$lib/api/client";
  import {
    completeSession,
    loadSessionSummary,
    saveReconciliation,
    saveReflection,
    type StudySessionSummary,
  } from "$lib/api/study";
  import { m } from "$lib/paraglide/messages.js";
  import { anchorCard } from "$lib/study/deck";
  import { sessionDrafts } from "$lib/study/drafts";
  import { percent } from "$lib/study/percent";
  import { createStudyRuntime } from "$lib/study/runtime";
  import type { PageData } from "./$types";

  type Props = { data: PageData };
  type Refusal = "reconciliation" | "pacing" | "unavailable";

  let { data }: Props = $props();

  const anchorQuestion = $derived(anchorCard(data.questions));
  // The post-test answers the anchor a second time on purpose, so it is not
  // filtered by the attempted ids the way the practice deck is. What ends it
  // is the server's own count of post-test attempts: without that, a reload
  // here would ask for a third answer and write a second post-test row into
  // the mean.
  const postTestAnswered = $derived(data.summary.attempts.post_test > 0);
  const context = $derived({
    csrfToken: data.csrfToken ?? "",
    learningPathId: data.learningPathId,
    sessionId: data.sessionId,
  });

  // Rebuilt when the session changes, or when its deck grows — and not when
  // some unrelated `invalidateAll` hands the page a fresh data object, which
  // would discard the answer a learner is part-way through writing.
  const runtime = $derived.by(() => {
    // The one tracked read: rebuilding on anything else would throw away a
    // card in progress.
    void `${data.sessionId}:${data.questions.length}:${data.summary.attempts.post_test}`;
    return untrack(() => {
      const question = data.summary.attempts.post_test > 0
        ? undefined
        : anchorCard(data.questions);
      return question
        ? createStudyRuntime({
            csrfToken: data.csrfToken ?? "",
            learningPathId: data.learningPathId,
            sessionId: data.sessionId,
            questions: [question],
            pacing: data.pacing,
            phase: "post_test",
          })
        : null;
    });
  });

  const reflectionDraft = untrack(() =>
    sessionDrafts(data.sessionId, "reflection"),
  );
  let reflection = $state(reflectionDraft.read("text") ?? "");
  let elapsedSeconds = $state(0);
  // The results open on a reflection the server holds, so a reload after
  // opening them comes back to them instead of asking for a second one.
  let summary = $state<StudySessionSummary | null>(
    untrack(() => (data.summary.reflected ? data.summary : null)),
  );
  let submitting = $state(false);
  let revealFailed = $state(false);

  // The server's RECONCILIATION_MAX_CHARS.
  const RECONCILIATION_MAX_CHARS = 1000;
  const reconciliationDraft = untrack(() =>
    sessionDrafts(data.sessionId, "reconciliation"),
  );
  let reconciliation = $state(reconciliationDraft.read("text") ?? "");
  let reconciliationSaved = false;
  let finishing = $state(false);
  let finishFailure = $state<Refusal | null>(null);

  const secondsLeft = $derived(
    Math.max(data.pacing.reflection_min_seconds - elapsedSeconds, 0),
  );
  const postTestDone = $derived(
    postTestAnswered || runtime === null || runtime.store.remaining === 0,
  );
  const reflectionWritten = $derived(reflection.trim().length > 0);
  const canReveal = $derived(postTestDone && reflectionWritten && secondsLeft <= 0);
  const finished = $derived(summary?.session.completed_at != null);
  const reconciliationWritten = $derived(
    reconciliation.trim().length > 0 || summary?.reconciliation != null,
  );
  // The server refuses to close a missed prediction without this; the button
  // only says so first.
  const canFinish = $derived(
    summary !== null &&
      (!summary.reconciliation_required || reconciliationWritten),
  );

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

  // The countdown is the pedagogy, not a spinner: the floor comes from the
  // server (GET /api/study/pacing) so shortening it is a deployment change,
  // and the results stay closed until it elapses.
  $effect(() => {
    if (!postTestDone) {
      return;
    }
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
    revealFailed = false;
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
      reflectionDraft.clear("text");
      // The session stays open: it closes on Finish, once the learner has
      // seen the gap and, where the prediction missed, explained it.
      summary = await loadSessionSummary(data.sessionId);
    } catch {
      revealFailed = true;
    } finally {
      submitting = false;
    }
  }

  async function finish() {
    if (summary === null || !canFinish || finishing) {
      return;
    }
    finishing = true;
    finishFailure = null;
    try {
      const text = reconciliation.trim();
      if (text && summary.reconciliation === null && !reconciliationSaved) {
        await saveReconciliation(context, {
          reconciliationText: text,
          requestId: crypto.randomUUID(),
        });
        // A retry after the completion failed must not write it twice.
        reconciliationSaved = true;
      }
      await completeSession(context);
      reconciliationDraft.clear("text");
      await goto(resolve("/study", {}));
    } catch (error) {
      finishFailure = refusal(error);
    } finally {
      finishing = false;
    }
  }

  /**
   * A 412 is the server holding a precondition, not an outage: telling the
   * learner to "try again shortly" would be both wrong and rude.
   */
  function refusal(error: unknown): Refusal {
    if (!(error instanceof SophiaApiError) || error.status !== 412) {
      return "unavailable";
    }
    return error.detail.params.required === "reconciliation"
      ? "reconciliation"
      : "pacing";
  }

  function refusalMessage(reason: Refusal): string {
    switch (reason) {
      case "reconciliation":
        return m.study_reconcile_refused();
      case "pacing":
        return m.study_reflection_too_soon();
      default:
        return m.study_not_available();
    }
  }

  function reconcilePrompt(current: StudySessionSummary): string {
    const figures = {
      predicted: percent(current.predicted),
      measured: percent(current.measured),
    };
    return current.reconciliation_required
      ? m.study_reconcile_prompt(figures)
      : m.study_reconcile_prompt_optional(figures);
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

{#if runtime && !postTestDone && !summary}
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
    <label class="prompt" for="study-reflection">
      {m.study_reflection_prompt()}
    </label>
    <textarea
      id="study-reflection"
      rows="6"
      bind:value={reflection}
      oninput={(event) =>
        reflectionDraft.write("text", event.currentTarget.value)}
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
    {#if revealFailed}
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
        {#if summary.prediction_reason}
          <dd class="reason" data-testid="prediction-reason">
            {m.study_prediction_reason_shown({
              reason: summary.prediction_reason,
            })}
          </dd>
        {/if}
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
  </section>

  {#if summary.band !== "unknown" && (summary.reconciliation || !finished)}
    <section class="reconcile" aria-labelledby="study-reconcile-heading">
      <h2 id="study-reconcile-heading">{m.study_reconcile_heading()}</h2>
      {#if summary.reconciliation}
        <p class="prompt">{m.study_reconcile_yours()}</p>
        <blockquote data-testid="reconciliation">
          {summary.reconciliation.reconciliation_text}
        </blockquote>
      {:else if !finished}
        <label class="prompt" for="study-reconciliation">
          {reconcilePrompt(summary)}
        </label>
        <textarea
          id="study-reconciliation"
          rows="3"
          maxlength={RECONCILIATION_MAX_CHARS}
          bind:value={reconciliation}
          oninput={(event) =>
            reconciliationDraft.write("text", event.currentTarget.value)}
          aria-describedby="study-reconcile-status"
        ></textarea>
        <p id="study-reconcile-status" class="status" aria-live="polite">
          {#if !summary.reconciliation_required}
            {m.study_reconcile_optional()}
          {:else if !reconciliationWritten}
            {m.study_reconcile_required()}
          {/if}
        </p>
      {/if}
    </section>
  {/if}

  <div class="finish">
    {#if finished}
      <a href={resolve("/study", {})}>{m.study_finish()}</a>
    {:else}
      <button
        type="button"
        disabled={!canFinish || finishing}
        onclick={() => void finish()}
      >
        {m.study_finish()}
      </button>
      {#if finishFailure}
        <p class="error" role="alert">{refusalMessage(finishFailure)}</p>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .posttest,
  .reflection,
  .results,
  .reconcile,
  .finish {
    display: grid;
    max-width: 52rem;
    gap: 0.7rem;
    margin-bottom: 1rem;
  }

  .reflection,
  .results,
  .reconcile {
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

  .status,
  .band,
  .legacy,
  .error,
  blockquote {
    margin: 0;
    overflow-wrap: anywhere;
  }

  blockquote {
    border-left: 3px solid var(--border-strong);
    padding-left: 0.7rem;
  }

  .prompt {
    font-weight: 700;
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

  dd.reason {
    color: var(--muted);
    font-size: 0.9rem;
    font-weight: 400;
  }

  .error {
    color: var(--danger);
  }

</style>
