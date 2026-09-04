<script lang="ts">
  import ProvenanceBadge from "../ProvenanceBadge.svelte";
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
</div>

<style>
  .card-prompt {
    display: grid;
    min-width: 0;
    gap: 0.5rem;
  }

  h2 {
    margin: 0;
    font-size: clamp(1.1rem, 1rem + 0.6vw, 1.4rem);
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
</style>
