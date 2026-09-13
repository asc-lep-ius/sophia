<script lang="ts">
  import { resolve } from "$app/paths";
  import BarFigure from "$lib/components/dashboard/BarFigure.svelte";
  import DueDate from "$lib/components/chronos/DueDate.svelte";
  import FilterDrawer from "$lib/components/content/FilterDrawer.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import { DEADLINE_OUTCOMES } from "$lib/chronos/deadlines";
  import { barRow } from "$lib/dashboard/figures";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const historyPath = resolve("/chronos/history", {});
  const chronosPath = resolve("/chronos", {});

  const outcomeLabels = {
    all: m.chronos_outcome_all,
    on_time: m.chronos_outcome_on_time,
    late: m.chronos_outcome_late,
    missed: m.chronos_outcome_missed,
  } as const;

  const metrics = $derived(data.calibration.data);
  const bars = $derived(
    barRow(
      metrics.map((metric) => ({
        display: m.chronos_effort_error_hours({
          hours: metric.mean_absolute_error.toFixed(2),
        }),
        key: metric.domain,
        label: metric.domain,
        value: metric.mean_absolute_error,
      })),
    ),
  );
  /** Domains whose figure rests on one or two finished deadlines. */
  const sparseCount = $derived(
    metrics.filter((metric) => metric.sample_count < 3).length,
  );
</script>

<PageHeader
  heading={m.chronos_history_heading()}
  summary={m.chronos_history_summary()}
/>

{#if data.learningPathId === null}
  <p class="notice">{m.dashboard_no_learning_path()}</p>
{:else}
  <FilterDrawer action={historyPath} open={data.drawerOpen}>
    {#snippet fields()}
      <div class="field">
        <label for="history-outcome">{m.chronos_history_filter_outcome()}</label>
        <select id="history-outcome" name="outcome">
          {#each DEADLINE_OUTCOMES as outcome (outcome)}
            <option value={outcome} selected={outcome === data.outcome}>
              {outcomeLabels[outcome]()}
            </option>
          {/each}
        </select>
      </div>
    {/snippet}
  </FilterDrawer>

  <PanelSection
    id="chronos-history"
    heading={m.chronos_history_list_heading()}
    status={data.rows.status}
    isEmpty={data.rows.data.length === 0}
    note={m.chronos_history_count({
      shown: data.rows.data.length,
      total: data.totalCount,
    })}
  >
    {#snippet empty()}
      <div class="empty-state">
        {#if data.outcome !== "all"}
          <p class="empty-title">{m.chronos_history_no_matches_title()}</p>
          <p class="empty-body">{m.chronos_history_no_matches_body()}</p>
          <!--
            The filter searched one page of history, not all of it. Without
            this, "nothing matched" reads as a fact about the whole record.
          -->
          {#if data.totalCount >= data.limit}
            <p class="empty-body">
              {m.chronos_history_capped({ limit: data.limit })}
            </p>
          {/if}
          <a href={historyPath}>{m.content_filters_reset()}</a>
        {:else}
          <p class="empty-title">{m.chronos_history_empty_title()}</p>
          <p class="empty-body">{m.chronos_history_empty_body()}</p>
          <a href={chronosPath}>{m.chronos_history_back()}</a>
        {/if}
      </div>
    {/snippet}

    <ul class="rows">
      {#each data.rows.data as row (row.deadline.id)}
        <li class="row">
          <div class="row-head">
            <span class="outcome" data-outcome={row.outcome}
              >{outcomeLabels[row.outcome]()}</span
            >
            <h3>{row.deadline.name}</h3>
          </div>
          <p class="course">{row.deadline.learning_path_name}</p>
          <DueDate
            dueAt={row.deadline.due_at}
            locale={data.uiLocale}
            now={data.now}
          />
          <p class="reflection">
            {row.reflected
              ? m.chronos_history_reflected()
              : m.chronos_history_not_reflected()}
          </p>
        </li>
      {/each}
    </ul>

    <!--
      Said plainly rather than left to be inferred: nothing in the history data
      records when a deadline was finished, only whether it was reflected on.
      A learner who never sees a "late" row deserves to know that the surface
      cannot produce one, instead of concluding they have never been late.
    -->
    <p class="caveat">{m.chronos_history_late_unavailable()}</p>
    {#if data.totalCount >= data.limit}
      <!--
        The list is one page deep, not the whole record. Classifying a row
        costs one request per row, so the page asks for fewer than the
        endpoint would give it — and a learner who cannot tell a capped list
        from a complete one will read their own history as shorter than it is.
      -->
      <p class="caveat">{m.chronos_history_capped({ limit: data.limit })}</p>
    {/if}
  </PanelSection>

  <PanelSection
    id="chronos-effort"
    heading={m.chronos_effort_heading()}
    status={data.calibration.status}
    isEmpty={metrics.length === 0}
    note={sparseCount > 0
      ? m.chronos_effort_sparse({ count: sparseCount })
      : undefined}
  >
    {#snippet empty()}
      <p class="empty-body">{m.chronos_effort_empty()}</p>
    {/snippet}

    <BarFigure
      id="chronos-effort-figure"
      bars={bars}
      caption={m.chronos_effort_caption()}
      labelHeading={m.chronos_effort_domain()}
      summary={m.chronos_effort_summary({ count: metrics.length })}
      valueHeading={m.chronos_effort_abs_error()}
    />

    <table class="samples">
      <thead>
        <tr>
          <th scope="col">{m.chronos_effort_domain()}</th>
          <th scope="col">{m.chronos_effort_mean_error()}</th>
          <th scope="col">{m.chronos_effort_samples()}</th>
        </tr>
      </thead>
      <tbody>
        {#each metrics as metric (metric.domain)}
          <tr>
            <th scope="row">{metric.domain}</th>
            <td
              >{m.chronos_effort_error_hours({
                hours: metric.mean_error.toFixed(2),
              })}</td
            >
            <td>{metric.sample_count}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </PanelSection>

  <p class="back">
    <a href={chronosPath}>{m.chronos_history_back()}</a>
  </p>
{/if}

<style>
  .field {
    display: grid;
    min-width: 0;
    gap: 0.25rem;
  }

  label {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  select {
    min-height: 2.75rem;
    min-width: 0;
    width: 100%;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.7rem;
    font: inherit;
  }

  .rows {
    display: grid;
    min-width: 0;
    gap: 0.75rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.4rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-raised);
    padding: 0.8rem;
  }

  .row-head {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.5rem;
  }

  .outcome {
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-size: 0.78rem;
    overflow-wrap: anywhere;
  }

  .outcome[data-outcome="missed"] {
    border-color: var(--danger);
    color: var(--danger);
  }

  h3 {
    margin: 0;
    font-size: 1rem;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  .course,
  .reflection,
  .caveat,
  .notice,
  .empty-body,
  .empty-title,
  .back {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .course,
  .reflection,
  .caveat,
  .notice,
  .empty-body {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .caveat {
    margin-top: 0.75rem;
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

  .back {
    margin-top: 0.75rem;
  }

  .samples {
    width: 100%;
    min-width: 0;
    border-collapse: collapse;
    font-size: 0.85rem;
    table-layout: fixed;
  }

  .samples th,
  .samples td {
    border-bottom: 1px solid var(--border);
    padding: 0.35rem 0.25rem;
    text-align: start;
    overflow-wrap: anywhere;
  }

  .samples thead th {
    color: var(--muted);
    font-weight: 700;
  }

  .samples tbody th {
    font-weight: 400;
  }
</style>
