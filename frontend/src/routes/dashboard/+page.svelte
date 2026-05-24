<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { m } from '$lib/paraglide/messages.js';

  const tiles = [
    { caption: m.dashboard_due_caption, value: m.dashboard_due_value },
    { caption: m.dashboard_confidence_caption, value: m.dashboard_confidence_value },
    { caption: m.dashboard_latency_caption, value: m.dashboard_latency_value }
  ];
</script>

<PageHeader heading={m.dashboard_heading()} summary={m.dashboard_summary()} />

<section class="dashboard-panel" aria-labelledby="dashboard-panel-title">
  <h2 id="dashboard-panel-title">{m.dashboard_panel_title()}</h2>
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
    .tile-grid {
      grid-template-columns: 1fr;
    }
  }
</style>