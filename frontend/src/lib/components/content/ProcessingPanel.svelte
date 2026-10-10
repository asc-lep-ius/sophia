<script lang="ts">
  import { enhance } from "$app/forms";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import {
    itemOutcome,
    TRANSCRIPTION_LANGUAGES,
    type IngestionJob,
    type IngestionSourceStatus,
    type IngestionStatus,
    type ProcessOutcome,
  } from "$lib/content/ingestion";
  import type { Panel } from "$lib/dashboard/panels";
  import { m } from "$lib/paraglide/messages.js";

  type Props = {
    learningPathId: number | null;
    status: Panel<IngestionStatus | null>;
    sources: IngestionSourceStatus[];
    processResult: { outcome: ProcessOutcome; reason: string } | null;
    processFailed: boolean;
    settingsSaved: boolean;
    settingsFailed: boolean;
  };

  let {
    learningPathId,
    status,
    sources,
    processResult,
    processFailed,
    settingsSaved,
    settingsFailed,
  }: Props = $props();

  const current = $derived(status.data);
  const job = $derived(current?.job ?? null);
  const jobActive = $derived(
    job?.state === "queued" || job?.state === "processing",
  );
  const workerBlocked = $derived(
    current !== null && !current.worker.available && !jobActive,
  );
  const itemCount = $derived(
    sources.reduce((count, source) => count + source.items.length, 0),
  );

  const stageLabels: Record<string, () => string> = {
    captions: m.content_processing_stage_captions,
    download: m.content_processing_stage_download,
    transcribe: m.content_processing_stage_transcribe,
    index: m.content_processing_stage_index,
    topics: m.content_processing_stage_topics,
    media: m.content_processing_stage_download,
    knowledge: m.content_processing_stage_index,
  };

  const languageLabels: Record<string, () => string> = {
    "": m.content_processing_language_auto,
    de: m.content_processing_language_de,
    en: m.content_processing_language_en,
  };

  function jobLine(current: IngestionJob | null): string {
    if (current === null) {
      return m.content_processing_state_none();
    }
    switch (current.state) {
      case "queued":
        return m.content_processing_state_queued();
      case "processing":
        return m.content_processing_state_processing({
          stage: (
            stageLabels[current.stage ?? ""] ??
            m.content_processing_stage_download
          )(),
        });
      case "failed":
        return m.content_processing_state_failed({
          reason: current.error ?? "",
        });
      default:
        return m.content_processing_state_ready({
          at: current.finished_at ?? "",
        });
    }
  }

  function processMessage(
    result: { outcome: ProcessOutcome; reason: string } | null,
  ): string | null {
    if (result === null) {
      return null;
    }
    switch (result.outcome) {
      case "started":
        return m.content_processing_started();
      case "already_running":
        return m.content_processing_already_running();
      default:
        return m.content_processing_unavailable({ reason: result.reason });
    }
  }
</script>

<PanelSection
  id="content-processing"
  heading={m.content_processing_heading()}
  status={status.status}
  isEmpty={learningPathId === null || current === null}
>
  {#snippet empty()}
    <p class="lead">{m.content_processing_no_course()}</p>
  {/snippet}

  {#if current !== null}
    <p class="lead">{m.content_processing_summary()}</p>

    <p class="job" role="status" aria-live="polite" data-job-state={job?.state ?? "none"}>
      {jobLine(job)}
    </p>

    {#if workerBlocked}
      <p class="error" role="alert">
        {m.content_processing_worker_unavailable({
          reason: current.worker.reason,
        })}
      </p>
    {/if}

    <form class="actions" method="POST" action="?/process" use:enhance>
      <button type="submit" disabled={jobActive || workerBlocked}>
        {m.content_processing_start()}
      </button>
    </form>

    {#if processResult}
      <p
        class:error={processResult.outcome !== "started"}
        class="outcome"
        role={processResult.outcome === "started" ? "status" : "alert"}
      >
        {processMessage(processResult)}
      </p>
    {/if}
    {#if processFailed}
      <p class="error" role="alert">{m.content_processing_failed_to_start()}</p>
    {/if}

    <form class="settings" method="POST" action="?/settings" use:enhance>
      <p class="following">
        {current.settings.subscribed
          ? m.content_processing_following()
          : m.content_processing_not_following()}
      </p>
      <input
        type="hidden"
        name="subscribed"
        value={current.settings.subscribed ? "false" : "true"}
      />
      <input
        type="hidden"
        name="transcription_language"
        value={current.settings.transcription_language ?? ""}
      />
      <button type="submit" class="secondary">
        {current.settings.subscribed
          ? m.content_processing_unfollow()
          : m.content_processing_follow()}
      </button>
    </form>

    <form class="settings language" method="POST" action="?/settings" use:enhance>
      <input
        type="hidden"
        name="subscribed"
        value={current.settings.subscribed ? "true" : "false"}
      />
      <label for="transcription-language">
        {m.content_processing_language_label()}
      </label>
      <select id="transcription-language" name="transcription_language">
        {#each TRANSCRIPTION_LANGUAGES as language (language)}
          <option
            value={language}
            selected={language === (current.settings.transcription_language ?? "")}
          >
            {(languageLabels[language] ?? m.content_processing_language_auto)()}
          </option>
        {/each}
      </select>
      <button type="submit" class="secondary">
        {m.content_processing_language_save()}
      </button>
    </form>

    {#if settingsSaved}
      <p class="outcome" role="status">{m.content_processing_settings_saved()}</p>
    {/if}
    {#if settingsFailed}
      <p class="error" role="alert">{m.content_processing_settings_failed()}</p>
    {/if}

    <h3>{m.content_processing_items_heading()}</h3>
    {#if itemCount === 0}
      <p class="hint">{m.content_processing_no_items()}</p>
    {:else}
      <ul class="items">
        {#each sources as source (source.id)}
          {#each source.items as item (item.id)}
            {@const outcome = itemOutcome(item)}
            <li data-outcome={outcome}>
              <span class="title">
                {#if item.sequence_number !== null}
                  {m.content_processing_item_number({
                    number: item.sequence_number,
                  })}
                {/if}
                {item.title}
              </span>
              <span class="state" class:failed={outcome === "failed"}>
                {#if outcome === "ready"}
                  {m.content_processing_item_ready()}
                {:else if outcome === "failed"}
                  {m.content_processing_item_failed({
                    reason: item.failure_reason ?? "",
                  })}
                {:else if outcome === "processing"}
                  {m.content_processing_item_processing()}
                {:else}
                  {m.content_processing_item_pending()}
                {/if}
              </span>
            </li>
          {/each}
        {/each}
      </ul>
    {/if}
  {/if}
</PanelSection>

<style>
  .lead,
  .hint,
  .following {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .job,
  .outcome,
  .error {
    margin: 0.5rem 0 0;
    overflow-wrap: anywhere;
  }

  .error {
    color: var(--danger);
  }

  h3 {
    margin: 1rem 0 0.4rem;
    font-size: 0.95rem;
  }

  .actions,
  .settings {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    margin-top: 0.75rem;
  }

  button {
    min-height: 2.75rem;
    min-width: 2.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    padding: 0.55rem 0.9rem;
    overflow-wrap: anywhere;
  }

  button:disabled {
    opacity: 0.6;
  }

  button.secondary {
    background: var(--surface-raised);
    color: var(--text);
  }

  select {
    min-height: 2.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.4rem 0.6rem;
  }

  .items {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .items li {
    display: flex;
    min-width: 0;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
    border-top: 1px solid var(--border);
    padding-top: 0.4rem;
    overflow-wrap: anywhere;
  }

  .state {
    flex: 0 1 auto;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .state.failed {
    color: var(--danger);
  }

  @media (max-width: 560px) {
    .items li {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.15rem;
    }
  }
</style>
