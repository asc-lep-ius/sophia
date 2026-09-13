<script lang="ts">
  import { enhance } from "$app/forms";
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages.js";
  import type { ActionData, PageData } from "./$types";

  type Props = {
    data: PageData;
    form: ActionData;
  };

  let { data, form }: Props = $props();

  const errorMessage = $derived(errorText(form?.error));

  function errorText(code: string | undefined): string | null {
    switch (code) {
      case "quickstart.topics_required":
        return m.quickstart_topics_required();
      case "quickstart.no_learning_path":
        return m.dashboard_no_learning_path();
      case "quickstart.save_failed":
        return m.quickstart_save_failed();
      default:
        return code ? m.quickstart_save_failed() : null;
    }
  }
</script>

<section class="step" aria-labelledby="quickstart-topics-heading">
  <h2 id="quickstart-topics-heading">{m.quickstart_topics_heading()}</h2>
  <p>{m.quickstart_topics_body()}</p>

  {#if data.topics.length > 0}
    <div class="known">
      <p class="known-title">{m.quickstart_topics_known()}</p>
      <ul>
        {#each data.topics as topic (topic.topic)}
          <li>{topic.topic}</li>
        {/each}
      </ul>
    </div>
  {:else}
    <p class="empty">{m.quickstart_topics_empty()}</p>
  {/if}

  <form method="POST" action="?/save" use:enhance>
    <label for="quickstart-topics">{m.quickstart_topics_label()}</label>
    <p id="quickstart-topics-hint" class="hint">{m.quickstart_topics_hint()}</p>
    <textarea
      id="quickstart-topics"
      name="topics"
      rows="5"
      aria-describedby="quickstart-topics-hint"
    ></textarea>
    <button type="submit">{m.quickstart_topics_save()}</button>
  </form>

  {#if errorMessage}
    <p class="error" role="alert">{errorMessage}</p>
  {/if}

  <a href={resolve("/quickstart/predict", {})}>{m.quickstart_skip()}</a>
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

  .empty,
  .hint {
    color: var(--muted);
    font-size: 0.9rem;
  }

  .known {
    display: grid;
    min-width: 0;
    gap: 0.3rem;
  }

  .known-title {
    font-weight: 700;
  }

  ul {
    display: grid;
    gap: 0.2rem;
    margin: 0;
    padding-left: 1.2rem;
  }

  li {
    overflow-wrap: anywhere;
  }

  form {
    display: grid;
    width: 100%;
    min-width: 0;
    justify-items: start;
    gap: 0.35rem;
  }

  label {
    font-weight: 700;
  }

  textarea {
    width: 100%;
    min-width: 0;
    resize: vertical;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.65rem;
    font: inherit;
  }

  button,
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

  .error {
    color: var(--danger);
  }
</style>
