<script lang="ts">
  import { enhance } from "$app/forms";
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages.js";
  import { CONFIDENCE_RATINGS } from "$lib/quickstart/topics";
  import type { ActionData, PageData } from "./$types";

  type Props = {
    data: PageData;
    form: ActionData;
  };

  let { data, form }: Props = $props();

  const ratingLabels = {
    1: m.study_predict_1,
    2: m.study_predict_2,
    3: m.study_predict_3,
    4: m.study_predict_4,
    5: m.study_predict_5,
  } satisfies Record<(typeof CONFIDENCE_RATINGS)[number], () => string>;

  const errorMessage = $derived(errorText(form?.error));

  function errorText(code: string | undefined): string | null {
    switch (code) {
      case "quickstart.ratings_required":
        return m.quickstart_ratings_required();
      case "quickstart.no_learning_path":
        return m.dashboard_no_learning_path();
      default:
        return code ? m.quickstart_save_failed() : null;
    }
  }
</script>

<section class="step" aria-labelledby="quickstart-predict-heading">
  <h2 id="quickstart-predict-heading">{m.quickstart_predict_heading()}</h2>
  <p>{m.quickstart_predict_body()}</p>

  {#if data.topics.length === 0}
    <p class="empty">{m.quickstart_predict_empty()}</p>
    <a href={resolve("/quickstart/topics", {})}>{m.quickstart_predict_back()}</a>
  {:else}
    <form method="POST" action="?/save" use:enhance>
      {#each data.topics as topic (topic.topic)}
        <fieldset>
          <legend>{m.quickstart_predict_legend({ topic: topic.topic })}</legend>
          <div class="ratings">
            {#each CONFIDENCE_RATINGS as rating (rating)}
              <label>
                <input type="radio" name={`rating:${topic.topic}`} value={rating} />
                <span>{ratingLabels[rating]()}</span>
              </label>
            {/each}
          </div>
        </fieldset>
      {/each}
      <button type="submit">{m.quickstart_predict_save()}</button>
    </form>
  {/if}

  {#if errorMessage}
    <p class="error" role="alert">{errorMessage}</p>
  {/if}
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

  .empty {
    color: var(--muted);
  }

  form {
    display: grid;
    width: 100%;
    min-width: 0;
    justify-items: start;
    gap: 0.9rem;
  }

  fieldset {
    display: grid;
    width: 100%;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    border: 0;
    border-top: 1px solid var(--border);
    padding: 0.6rem 0 0;
  }

  legend {
    padding: 0;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .ratings {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(min(8rem, 100%), 1fr));
    gap: 0.4rem;
  }

  label {
    display: flex;
    min-height: 2.75rem;
    min-width: 0;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.35rem 0.6rem;
  }

  label span {
    overflow-wrap: anywhere;
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
