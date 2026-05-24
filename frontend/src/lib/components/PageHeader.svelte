<script lang="ts">
  type Props = {
    heading: string;
    summary: string;
  };

  let { heading, summary }: Props = $props();
</script>

<header class="page-header">
  <h1>{heading}</h1>
  <p>{summary}</p>
</header>

<style>
  .page-header {
    display: grid;
    max-width: 52rem;
    gap: 0.4rem;
    margin-bottom: 1rem;
  }

  h1 {
    margin: 0;
    font-size: clamp(1.65rem, 1.45rem + 0.7vw, 2.2rem);
    line-height: 1.1;
  }

  p {
    margin: 0;
    color: var(--muted);
    line-height: 1.55;
    overflow-wrap: anywhere;
  }
</style>