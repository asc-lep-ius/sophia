<script lang="ts">
  import { m } from "$lib/paraglide/messages.js";
  import type { components } from "$lib/api/schema";

  type Provenance = components["schemas"]["Provenance"];

  type Props = {
    provenance: Provenance;
  };

  let { provenance }: Props = $props();

  const authorLabel = $derived(
    provenance.generated_by === "model"
      ? m.study_provenance_model()
      : m.study_provenance_learner(),
  );
</script>

<!--
  Who wrote this card is not decoration: a learner rating their own recall
  against a model-generated question deserves to know that is what it is.
-->
<p class="provenance">
  <span class="author" data-agent={provenance.generated_by}>{authorLabel}</span>
  <span class="origin">{m.study_provenance_source({ origin: provenance.origin })}</span>
</p>

<style>
  .provenance {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    margin: 0;
    color: var(--muted);
    font-size: 0.8rem;
  }

  .author {
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    padding: 0.1rem 0.55rem;
    overflow-wrap: anywhere;
  }

  .author[data-agent="model"] {
    border-color: var(--accent-strong);
    color: var(--accent-strong);
  }

  .origin {
    overflow-wrap: anywhere;
  }
</style>
