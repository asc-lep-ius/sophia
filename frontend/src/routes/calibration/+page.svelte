<script lang="ts">
  import { resolve } from "$app/paths";
  import CalibrationFigure from "$lib/components/dashboard/CalibrationFigure.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import { calibrationView } from "$lib/calibration/insights";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const studyPath = resolve("/study", {});

  const view = $derived(calibrationView(data.ratings.data));

  const excluded = $derived.by(() => {
    const notes: string[] = [];
    if (view.legacyScoredCount > 0) {
      notes.push(
        m.calibration_legacy_excluded({ count: view.legacyScoredCount }),
      );
    }
    if (view.unmeasuredCount > 0) {
      notes.push(m.calibration_unmeasured({ count: view.unmeasuredCount }));
    }
    return notes;
  });
</script>

<PageHeader
  heading={m.calibration_heading()}
  summary={m.calibration_summary()}
/>

{#if data.learningPathId === null}
  <p class="notice">{m.dashboard_no_learning_path()}</p>
{:else}
  <PanelSection
    id="calibration-measured"
    heading={m.calibration_measured_heading()}
    status={data.ratings.status}
    isEmpty={view.measured.length === 0}
    note={view.hasReading
      ? m.calibration_reading({ count: view.measured.length })
      : m.calibration_reading_sparse({ count: view.measured.length })}
  >
    {#snippet empty()}
      <div class="empty-state">
        <p class="empty-title">{m.calibration_empty_title()}</p>
        <p class="empty-body">{m.calibration_empty_body()}</p>
        <a class="primary" href={studyPath}>{m.dashboard_open_study()}</a>
      </div>
    {/snippet}

    <!--
      What the figure is and is not. Predicted against measured, per topic, in
      the order the server returned; no line is fitted through them and no
      average is offered, because with a handful of ratings either would read
      as a verdict the data cannot support.
    -->
    <p class="interpretation">{m.calibration_interpretation()}</p>
    <CalibrationFigure id="calibration-pairs" rows={view.measured} />
  </PanelSection>

  {#if excluded.length > 0}
    <!--
      The rows kept out of the figure, counted where the learner can see them.
      The retired scorer (#97) recorded a perfect score for anything submitted,
      so those rows would not add noise to the picture above — they would make
      it say that the learner is perfectly calibrated. Dropping them silently
      would be its own kind of lie, so they are declared instead.
    -->
    <section class="excluded" aria-labelledby="calibration-excluded-heading">
      <h2 id="calibration-excluded-heading">
        {m.calibration_excluded_heading()}
      </h2>
      <ul>
        {#each excluded as note (note)}
          <li>{note}</li>
        {/each}
      </ul>
    </section>
  {/if}

  <PanelSection
    id="calibration-blind-spots"
    heading={m.calibration_blind_spot_heading()}
    status={data.ratings.status}
    isEmpty={view.blindSpots.length === 0}
    note={view.hasReading ? undefined : m.calibration_blind_spot_caveat()}
  >
    {#snippet empty()}
      <p class="empty-body">
        {view.measured.length === 0
          ? m.calibration_blind_spot_no_data()
          : m.calibration_blind_spot_none()}
      </p>
    {/snippet}

    <ul class="blind-spots">
      {#each view.blindSpots as spot (spot.topic)}
        <li>
          <span class="topic">{spot.topic}</span>
          <span class="gap"
            >{m.calibration_blind_spot_gap({ percent: spot.gapPercent })}</span
          >
        </li>
      {/each}
    </ul>
  </PanelSection>
{/if}

<style>
  .interpretation,
  .notice,
  .empty-body,
  .empty-title {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .interpretation,
  .notice,
  .empty-body {
    color: var(--muted);
    font-size: 0.9rem;
  }

  .empty-state {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.4rem;
  }

  .empty-title {
    font-weight: 700;
  }

  .excluded {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
    margin: 1rem 0;
  }

  h2 {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .excluded ul {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding-left: 1.1rem;
    color: var(--muted);
    font-size: 0.9rem;
  }

  .excluded li {
    overflow-wrap: anywhere;
  }

  .blind-spots {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .blind-spots li {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.35rem;
  }

  .topic,
  .gap {
    overflow-wrap: anywhere;
  }

  .gap {
    color: var(--muted);
    font-size: 0.85rem;
  }

  a.primary {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    padding: 0.5rem 0.9rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }
</style>
