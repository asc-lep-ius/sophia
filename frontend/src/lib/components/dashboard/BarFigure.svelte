<script lang="ts">
  import type { FigureBar } from "$lib/dashboard/figures";

  type Props = {
    id: string;
    caption: string;
    summary: string;
    labelHeading: string;
    valueHeading: string;
    bars: FigureBar[];
  };

  let { id, caption, summary, labelHeading, valueHeading, bars }: Props =
    $props();

  const ROW_HEIGHT = 10;
  const ROW_GAP = 4;

  const viewBoxHeight = $derived(
    Math.max(bars.length * (ROW_HEIGHT + ROW_GAP) - ROW_GAP, ROW_HEIGHT),
  );
</script>

<!--
  The table is the figure; the rectangles are a second rendering of it.
  `aria-hidden` on the drawing is not an omission — a screen reader that read
  both would hear every number twice, and the one it can act on is the table.
  See docs/frontend-dashboard-charts.md.
-->
<figure class="bar-figure" aria-describedby={`${id}-summary`}>
  <figcaption>{caption}</figcaption>
  <p id={`${id}-summary`} class="summary">{summary}</p>

  <svg
    class="marks"
    viewBox={`0 0 100 ${viewBoxHeight}`}
    preserveAspectRatio="none"
    style={`height: ${bars.length * 1.25}rem`}
    aria-hidden="true"
    focusable="false"
  >
    {#each bars as bar, index (bar.key)}
      <rect
        class="track"
        x="0"
        y={index * (ROW_HEIGHT + ROW_GAP)}
        width="100"
        height={ROW_HEIGHT}
      />
      <rect
        class="value"
        x="0"
        y={index * (ROW_HEIGHT + ROW_GAP)}
        width={bar.percent}
        height={ROW_HEIGHT}
      />
    {/each}
  </svg>

  <table>
    <thead>
      <tr>
        <th scope="col">{labelHeading}</th>
        <th scope="col">{valueHeading}</th>
      </tr>
    </thead>
    <tbody>
      {#each bars as bar (bar.key)}
        <tr>
          <th scope="row">{bar.label}</th>
          <td>{bar.display}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</figure>

<style>
  .bar-figure {
    display: grid;
    min-width: 0;
    gap: 0.5rem;
    margin: 0;
  }

  figcaption {
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .summary {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .marks {
    width: 100%;
    min-width: 0;
  }

  .track {
    fill: var(--accent-soft);
  }

  .value {
    fill: var(--accent-strong);
  }

  table {
    width: 100%;
    min-width: 0;
    border-collapse: collapse;
    font-size: 0.85rem;
    table-layout: fixed;
  }

  th,
  td {
    border-bottom: 1px solid var(--border);
    padding: 0.35rem 0.25rem;
    text-align: start;
    overflow-wrap: anywhere;
  }

  thead th {
    color: var(--muted);
    font-weight: 700;
  }

  tbody th {
    font-weight: 400;
  }
</style>
