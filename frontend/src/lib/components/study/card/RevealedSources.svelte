<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import type { components } from "$lib/api/schema";
  import { formatTimestamp } from "$lib/search/results";

  type SourceSpan = components["schemas"]["SourceSpan"];

  type Props = {
    spans?: SourceSpan[];
  };

  let { spans = [] }: Props = $props();

  type Excerpt = { text: string; location: string | null };

  const HEADING_ID = "study-card-sources";
  const MS_PER_SECOND = 1000;

  // A span that only locates its material carries nothing the learner can
  // read, so it cannot be what they grade themselves against.
  const excerpts = $derived(
    spans.flatMap((span): Excerpt[] =>
      span.excerpt ? [{ text: span.excerpt, location: locate(span) }] : [],
    ),
  );

  /** Which lecture, and where in it: what lets the learner go back and listen. */
  function locate(span: SourceSpan): string | null {
    if (span.start_ms == null) {
      return span.content_item_title ?? null;
    }
    const time = formatTimestamp(span.start_ms / MS_PER_SECOND);
    return span.content_item_title
      ? m.study_reveal_source_location({ lecture: span.content_item_title, time })
      : m.study_reveal_source_at({ time });
  }
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
      <figure>
        <blockquote>{excerpt.text}</blockquote>
        {#if excerpt.location}
          <figcaption>{excerpt.location}</figcaption>
        {/if}
      </figure>
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

  figure,
  blockquote {
    margin: 0;
  }

  figcaption {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }
</style>
