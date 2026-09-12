<script lang="ts">
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const firstTopic = $derived(data.topics.at(0)?.topic ?? null);
</script>

<section class="step" aria-labelledby="quickstart-done-heading">
  <h2 id="quickstart-done-heading">{m.quickstart_done_heading()}</h2>
  <p>{m.quickstart_done_body()}</p>
  {#if firstTopic}
    <p class="suggestion">{m.quickstart_done_suggestion({ topic: firstTopic })}</p>
  {/if}
  <div class="actions">
    <a class="primary" href={resolve("/study", {})}>{m.dashboard_open_study()}</a>
    <a href={resolve("/dashboard", {})}>{m.quickstart_done_dashboard()}</a>
  </div>
</section>

<style>
  .step {
    display: grid;
    max-width: 48rem;
    min-width: 0;
    justify-items: start;
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

  p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .suggestion {
    color: var(--muted);
  }

  .actions {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

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

  a.primary {
    border-color: var(--accent-strong);
    background: var(--accent);
    color: var(--on-accent);
  }
</style>
