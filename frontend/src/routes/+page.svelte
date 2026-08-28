<script lang="ts">
  import { resolve } from '$app/paths';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { m } from '$lib/paraglide/messages.js';
</script>

<PageHeader heading={m.home_heading()} summary={m.home_summary()} />

<section class="actions" aria-label={m.home_heading()}>
  <a class="primary" href={resolve('/study', {})}>{m.home_primary_action()}</a>
  <a href={resolve('/dashboard', {})}>{m.home_secondary_action()}</a>
</section>

<style>
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
  }

  a {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.65rem 0.95rem;
    color: var(--text);
    text-decoration: none;
  }

  .primary {
    border-color: var(--accent-strong);
    background: var(--accent);
    color: #ffffff;
  }
</style>