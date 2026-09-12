<script lang="ts">
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import {
    QUICKSTART_STEPS,
    stepFromPath,
    stepNumber,
    type QuickstartStep,
  } from "$lib/quickstart/steps";
  import type { Snippet } from "svelte";
  import type { LayoutData } from "./$types";

  type Props = {
    data: LayoutData;
    children?: Snippet;
  };

  let { data, children }: Props = $props();

  const current = $derived(stepFromPath(page.url.pathname));

  const stepRoutes = {
    welcome: "/quickstart/welcome",
    topics: "/quickstart/topics",
    predict: "/quickstart/predict",
    done: "/quickstart/done",
  } as const;

  const labels = {
    welcome: m.quickstart_step_welcome,
    topics: m.quickstart_step_topics,
    predict: m.quickstart_step_predict,
    done: m.quickstart_step_done,
  } satisfies Record<QuickstartStep, () => string>;
</script>

<PageHeader heading={m.quickstart_heading()} summary={m.quickstart_summary()} />

<!--
  The step list is read from the URL, so a reload, a back button or a shared
  link all land on the same step. Steps ahead of the current one are text
  rather than links: skipping the topics would leave the predictions with
  nothing to attach to.
-->
<nav class="steps" aria-label={m.quickstart_heading()}>
  <p class="position">
    {m.quickstart_step_position({
      step: stepNumber(current),
      total: QUICKSTART_STEPS.length,
    })}
  </p>
  <ol>
    {#each QUICKSTART_STEPS as step, index (step)}
      <li>
        {#if index <= QUICKSTART_STEPS.indexOf(current)}
          <a
            href={resolve(stepRoutes[step], {})}
            aria-current={step === current ? "step" : undefined}
          >
            {labels[step]()}
          </a>
        {:else}
          <span>{labels[step]()}</span>
        {/if}
      </li>
    {/each}
  </ol>
</nav>

{#if data.status === "unauthorized"}
  <p class="notice" role="status">{m.dashboard_panel_unauthorized()}</p>
{:else if data.status === "error"}
  <p class="notice error" role="status">{m.dashboard_panel_error()}</p>
{:else if children}
  {@render children()}
{/if}

<style>
  .steps {
    display: grid;
    max-width: 52rem;
    gap: 0.4rem;
    margin-bottom: 1rem;
  }

  ol {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li {
    min-width: 0;
  }

  a,
  span {
    display: inline-flex;
    min-height: 2.25rem;
    align-items: center;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.25rem 0.75rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }

  a[aria-current="step"] {
    border-color: var(--accent-strong);
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  span {
    color: var(--muted);
  }

  .position,
  .notice {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .notice.error {
    color: var(--danger);
  }
</style>
