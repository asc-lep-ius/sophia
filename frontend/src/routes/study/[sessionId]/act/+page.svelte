<script lang="ts">
  import { enhance } from "$app/forms";
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import StudyCard from "$lib/components/study/StudyCard.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import { StudyEventStream, type StudyStreamStatus } from "$lib/study/events";
  import { createStudyRuntime } from "$lib/study/runtime";
  import type { ActionData, PageData } from "./$types";

  type Props = { data: PageData; form: ActionData };

  let { data, form }: Props = $props();

  // The first card is the session's anchor question: it was answered on the
  // predict route and is answered again on reflect, which is what makes the
  // pre→post comparison a comparison rather than two unrelated numbers.
  //
  // Rebuilt only when the session changes. SvelteKit reuses this component
  // across a param change, so a runtime captured at init would keep serving a
  // session the learner has left; but an unrelated `invalidateAll` must not
  // rebuild it either, or a card in progress loses the answer being written.
  const runtime = $derived.by(() => {
    const sessionId = data.sessionId;
    return untrack(() =>
      createStudyRuntime({
        csrfToken: data.csrfToken ?? "",
        learningPathId: data.learningPathId,
        sessionId,
        questions: data.questions.slice(1),
        pacing: data.pacing,
        phase: "practice",
      }),
    );
  });

  let streamStatus = $state<StudyStreamStatus>("idle");

  const queueEmpty = $derived(runtime.store.remaining === 0);

  $effect(() => {
    const current = runtime;
    current.store.recordPromptShown();
    return () => current.destroy();
  });

  $effect(() => {
    const stream = new StudyEventStream({
      sessionId: data.sessionId,
      onStatus: (status) => (streamStatus = status),
    });
    stream.connect();
    return () => stream.close();
  });

  const streamLabel = $derived(
    streamStatus === "open"
      ? m.study_stream_open()
      : streamStatus === "closed"
        ? m.study_stream_closed()
        : m.study_stream_connecting(),
  );
</script>

<PageHeader heading={m.study_act_heading()} summary={m.study_act_summary()} />

<p class="stream" data-status={streamStatus} aria-live="polite">{streamLabel}</p>

{#if queueEmpty}
  <section class="queue-empty" aria-labelledby="study-queue-empty">
    <h2 id="study-queue-empty">{m.study_queue_empty()}</h2>
    <div class="queue-actions">
      <form method="POST" action="?/extend" use:enhance>
        <input
          type="hidden"
          name="topic"
          value={data.summary.session.topic}
        />
        <button type="submit">{m.study_extend()}</button>
      </form>
      <a
        href={resolve("/study/[sessionId]/reflect", {
          sessionId: String(data.sessionId),
        })}
      >
        {m.study_step_reflect()}
      </a>
    </div>
    {#if form?.error}
      <p class="error" role="alert">{m.study_extend_failed()}</p>
    {/if}
  </section>
{:else}
  <StudyCard store={runtime.store} />
{/if}

<style>
  .stream {
    display: inline-flex;
    min-height: 1.75rem;
    align-items: center;
    gap: 0.4rem;
    margin: 0 0 0.75rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    color: var(--muted);
    font-size: 0.8rem;
    overflow-wrap: anywhere;
  }

  .stream[data-status="open"] {
    border-color: var(--accent-strong);
    color: var(--accent-strong);
  }

  .queue-empty {
    display: grid;
    max-width: 52rem;
    gap: 0.75rem;
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

  .queue-actions {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  button,
  a {
    display: inline-flex;
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

  .error {
    margin: 0;
    color: var(--danger);
    overflow-wrap: anywhere;
  }
</style>
