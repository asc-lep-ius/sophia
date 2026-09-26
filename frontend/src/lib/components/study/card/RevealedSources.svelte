<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import type { components } from "$lib/api/schema";

  type SourceSpan = components["schemas"]["SourceSpan"];

  type Props = {
    spans?: SourceSpan[];
  };

  let { spans = [] }: Props = $props();

  const HEADING_ID = "study-card-sources";

  // A span that only locates its material carries nothing the learner can
  // read, so it cannot be what they grade themselves against.
  const excerpts = $derived(
    spans.flatMap((span) => (span.excerpt ? [span.excerpt] : [])),
  );
</script>

<!--
  The reveal shows the material the question was generated from, never the
  learner's own answer back: that is still in the field above, and echoing it
  gave the self-grade nothing to judge against (#109).
-->
{#if excerpts.length > 0}
  <section class="revealed" aria-labelledby={HEADING_ID}>
    <h3 id={HEADING_ID}>{m.study_reveal_sources()}</h3>
    {#each excerpts as excerpt, index (index)}
      <blockquote>{excerpt}</blockquote>
    {/each}
  </section>
{:else}
  <p class="revealed free-recall">{m.study_reveal_free_recall()}</p>
{/if}

<style>
  .revealed {
    display: grid;
    min-width: 0;
    gap: 0.5rem;
    margin: 0;
    border-left: 3px solid var(--accent-strong);
    padding-left: 0.75rem;
  }

  h3 {
    margin: 0;
    font-size: 0.9rem;
    color: var(--muted);
    overflow-wrap: anywhere;
  }

  blockquote,
  .free-recall {
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }

  blockquote {
    margin: 0;
  }
</style>
