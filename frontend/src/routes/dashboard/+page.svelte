<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { m } from '$lib/paraglide/messages.js';
  import type { PageData } from './$types';

  type Props = {
    data: PageData;
  };

  const { data }: Props = $props();

  const tiles = [
    { caption: m.dashboard_due_caption, value: m.dashboard_due_value },
    { caption: m.dashboard_confidence_caption, value: m.dashboard_confidence_value },
    { caption: m.dashboard_latency_caption, value: m.dashboard_latency_value }
  ];

  const readyLabels = {
    ready: m.dashboard_api_ready,
    not_ready: m.dashboard_api_waiting,
    unknown: m.dashboard_api_offline
  } satisfies Record<PageData['apiReady'], () => string>;

  const readyLabel = $derived(readyLabels[data.apiReady]());
</script>

<PageHeader heading={m.dashboard_heading()} summary={m.dashboard_summary()} />

<section class="dashboard-panel" aria-labelledby="dashboard-panel-title">
  <div class="panel-title-row">
    <h2 id="dashboard-panel-title">{m.dashboard_panel_title()}</h2>
    <span class:muted-status={data.apiReady !== 'ready'}>{readyLabel}</span>
  </div>
  <div class="tile-grid">
    {#each tiles as tile (tile.caption)}
      <article>
        <strong>{tile.value()}</strong>
        <span>{tile.caption()}</span>
      </article>
    {/each}
  </div>
</section>

<style>
  .dashboard-panel {
    display: grid;
    gap: 1rem;
    max-width: 64rem;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
  }

  .panel-title-row {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .panel-title-row span {
    flex: none;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.2rem 0.55rem;
    color: var(--muted);
    font-size: 0.8rem;
    line-height: 1.2;
  }

  .panel-title-row span:not(.muted-status) {
    border-color: color-mix(in srgb, var(--accent), var(--border) 45%);
    color: var(--text);
  }

  .tile-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
  }

  article {
    display: grid;
    min-width: 0;
    gap: 0.35rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  strong,
  span {
    overflow-wrap: anywhere;
  }

  strong {
    font-size: 1.35rem;
  }

  span {
    color: var(--muted);
  }

  @media (max-width: 760px) {
    .panel-title-row {
      align-items: flex-start;
      flex-direction: column;
    }

    .tile-grid {
      grid-template-columns: 1fr;
    }
  }
</style>