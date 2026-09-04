<script lang="ts">
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages.js";
  import type { Snippet } from "svelte";
  import type { LayoutData } from "./$types";

  type Props = {
    data: LayoutData;
    children?: Snippet;
  };

  let { data, children }: Props = $props();

  const steps = [
    { slug: "predict", route: "/study/[sessionId]/predict", label: () => m.study_step_predict() },
    { slug: "act", route: "/study/[sessionId]/act", label: () => m.study_step_act() },
    { slug: "reflect", route: "/study/[sessionId]/reflect", label: () => m.study_step_reflect() },
  ] as const;

  const currentStep = $derived(
    Math.max(
      steps.findIndex((step) => page.url.pathname.endsWith(`/${step.slug}`)),
      0,
    ),
  );
</script>

<nav class="cycle" aria-label={m.study_heading()}>
  <p class="position">
    {m.study_step_position({ step: currentStep + 1, total: steps.length })}
  </p>
  <ol>
    {#each steps as step, index (step.slug)}
      <li>
        <!--
          A step the learner has not reached is not a link: the cycle only
          means anything in order, and skipping the prediction would leave
          nothing to compare the result against.
        -->
        {#if index <= currentStep}
          <a
            href={resolve(step.route, { sessionId: String(data.sessionId) })}
            aria-current={index === currentStep ? "step" : undefined}
          >
            {step.label()}
          </a>
        {:else}
          <span>{step.label()}</span>
        {/if}
      </li>
    {/each}
  </ol>
  <p class="topic">{data.summary.session.topic}</p>
</nav>

{#if children}
  {@render children()}
{/if}

<style>
  .cycle {
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
    counter-reset: step;
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
  .topic {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }
</style>
