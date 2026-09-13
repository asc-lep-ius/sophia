<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import type { Snippet } from "svelte";
  import type { PanelStatus } from "$lib/dashboard/panels";

  type Props = {
    id: string;
    heading: string;
    status: PanelStatus;
    isEmpty: boolean;
    children: Snippet;
    empty: Snippet;
    /** Shown beside the heading while the panel has something to qualify. */
    note?: string;
  };

  let { id, heading, status, isEmpty, children, empty, note }: Props = $props();
</script>

<!--
  Every panel renders one of four things and says which: the data, a designed
  empty state, a scope the learner does not have, or a service that did not
  answer. A panel that silently renders nothing for the last two teaches the
  learner to distrust the ones that do have data.
-->
<section class="panel" aria-labelledby={`${id}-heading`}>
  <div class="panel-head">
    <h2 id={`${id}-heading`}>{heading}</h2>
    {#if note}
      <p class="note">{note}</p>
    {/if}
  </div>

  {#if status === "unauthorized"}
    <p class="state" role="status">{m.dashboard_panel_unauthorized()}</p>
  {:else if status === "error"}
    <p class="state error" role="status">{m.dashboard_panel_error()}</p>
  {:else if isEmpty}
    {@render empty()}
  {:else}
    {@render children()}
  {/if}
</section>

<style>
  .panel {
    display: grid;
    min-width: 0;
    align-content: start;
    gap: 0.75rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  .panel-head {
    display: grid;
    min-width: 0;
    gap: 0.2rem;
  }

  h2 {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .note,
  .state {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .state.error {
    color: var(--danger);
  }
</style>
