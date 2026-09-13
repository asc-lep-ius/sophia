<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import { ratioPercent, type CalibrationRow } from "$lib/dashboard/figures";

  type Props = {
    id: string;
    rows: CalibrationRow[];
  };

  let { id, rows }: Props = $props();

  const ROW_HEIGHT = 8;
  const ROW_GAP = 3;
  const PAIR_HEIGHT = ROW_HEIGHT * 2 + 1;

  type Pair = {
    topic: string;
    predictedPercent: number;
    actualPercent: number;
    predictedText: string;
    actualText: string;
  };

  const pairs = $derived(
    rows.map(
      (row): Pair => ({
        topic: row.topic,
        predictedPercent: ratioPercent(row.predicted),
        actualPercent: ratioPercent(row.actual ?? 0),
        predictedText: percentText(row.predicted),
        actualText: percentText(row.actual ?? 0),
      }),
    ),
  );

  const viewBoxHeight = $derived(
    Math.max(pairs.length * (PAIR_HEIGHT + ROW_GAP) - ROW_GAP, PAIR_HEIGHT),
  );

  function percentText(value: number): string {
    return `${Math.round(value * 100)}%`;
  }
</script>

<figure class="calibration-figure" aria-describedby={`${id}-summary`}>
  <figcaption>{m.dashboard_calibration_caption()}</figcaption>
  <p id={`${id}-summary`} class="summary">
    {m.dashboard_calibration_figure_summary({ count: pairs.length })}
  </p>

  <svg
    class="marks"
    viewBox={`0 0 100 ${viewBoxHeight}`}
    preserveAspectRatio="none"
    style={`height: ${pairs.length * 1.6}rem`}
    aria-hidden="true"
    focusable="false"
  >
    {#each pairs as pair, index (pair.topic)}
      <rect
        class="predicted"
        x="0"
        y={index * (PAIR_HEIGHT + ROW_GAP)}
        width={pair.predictedPercent}
        height={ROW_HEIGHT}
      />
      <rect
        class="actual"
        x="0"
        y={index * (PAIR_HEIGHT + ROW_GAP) + ROW_HEIGHT + 1}
        width={pair.actualPercent}
        height={ROW_HEIGHT}
      />
    {/each}
  </svg>

  <table>
    <thead>
      <tr>
        <th scope="col">{m.dashboard_calibration_topic()}</th>
        <th scope="col">{m.dashboard_calibration_predicted()}</th>
        <th scope="col">{m.dashboard_calibration_actual()}</th>
      </tr>
    </thead>
    <tbody>
      {#each pairs as pair (pair.topic)}
        <tr>
          <th scope="row">{pair.topic}</th>
          <td>{pair.predictedText}</td>
          <td>{pair.actualText}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</figure>

<style>
  .calibration-figure {
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

  .predicted {
    fill: var(--accent-strong);
  }

  .actual {
    fill: var(--muted);
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
