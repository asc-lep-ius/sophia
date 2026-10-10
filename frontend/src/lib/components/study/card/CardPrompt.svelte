<script lang="ts">
  import ProvenanceBadge from "../ProvenanceBadge.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import type { StudyQuestion } from "$lib/api/study";

  type Props = {
    question: StudyQuestion;
    headingId?: string;
  };

  let { question, headingId = "study-card-prompt" }: Props = $props();

  const promptText = $derived(
    question.kind === "cloze"
      ? question.segments
          .map((segment) => (segment.blank ? "____" : (segment.text ?? "")))
          .join(" ")
      : question.prompt,
  );
</script>

<div class="card-prompt">
  <h2 id={headingId}>{promptText}</h2>
  <ProvenanceBadge provenance={question.provenance} />
  <!--
    Before the answer, not at the reveal: the learner should know the card is
    generic while writing, not find out after (#129).
  -->
  {#if question.fallback_reason === "index_unavailable"}
    <p class="fallback">{m.study_fallback_index_unavailable()}</p>
  {/if}
</div>

<style>
  .card-prompt {
    display: grid;
    min-width: 0;
    gap: 0.5rem;
  }

  .fallback {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
    overflow-wrap: anywhere;
  }

  h2 {
    margin: 0;
    font-size: clamp(1.1rem, 1rem + 0.6vw, 1.4rem);
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
</style>
