<script lang="ts">
  import { enhance } from "$app/forms";
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
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
      case "study.topic_required":
        return m.study_topic_required();
      case "study.learning_path_not_numeric":
        return m.study_no_learning_path();
      case "study.session_start_failed":
        return m.study_session_start_failed();
      default:
        return code ? m.study_not_available() : null;
    }
  }

</script>

<PageHeader heading={m.study_heading()} summary={m.study_summary()} />

{#if data.learningPathId === null}
  <p class="notice">{m.study_no_learning_path()}</p>
{:else}
  <section class="start" aria-labelledby="study-start-heading">
    <h2 id="study-start-heading">{m.study_start_heading()}</h2>
    <form method="POST" action="?/start" use:enhance>
      <label for="study-topic">{m.study_topic_label()}</label>
      <input id="study-topic" name="topic" type="text" required />
      <button type="submit">{m.study_start()}</button>
    </form>
    {#if errorMessage}
      <p class="error" role="alert">{errorMessage}</p>
    {/if}
  </section>

  <section class="sessions" aria-labelledby="study-sessions-heading">
    <h2 id="study-sessions-heading">{m.study_sessions_heading()}</h2>
    {#if data.sessions.length === 0}
      <p class="notice">{m.study_sessions_empty()}</p>
    {:else}
      <ul>
        {#each data.sessions as session (session.id)}
          <li>
            <div class="session-copy">
              <strong>{session.topic}</strong>
              <span>
                {session.completed_at
                  ? m.study_session_completed()
                  : m.study_session_in_progress()}
              </span>
            </div>
            {#if session.completed_at}
              <a
                href={resolve("/study/[sessionId]/reflect", {
                  sessionId: String(session.id),
                })}
              >
                {m.study_resume()}
              </a>
            {:else}
              <a
                href={resolve("/study/[sessionId]/act", {
                  sessionId: String(session.id),
                })}
              >
                {m.study_resume()}
              </a>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
{/if}

<style>
  .start,
  .sessions {
    display: grid;
    max-width: 48rem;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
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

  form {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
  }

  label {
    font-weight: 700;
  }

  input {
    min-height: 2.75rem;
    min-width: 0;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.7rem;
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

  ul {
    display: grid;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    border-top: 1px solid var(--border);
    padding-top: 0.5rem;
  }

  .session-copy {
    display: grid;
    min-width: 0;
    gap: 0.1rem;
  }

  .session-copy span {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .session-copy strong,
  .notice,
  .error {
    overflow-wrap: anywhere;
  }

  .notice {
    margin: 0;
    color: var(--muted);
  }

  .error {
    margin: 0;
    color: var(--danger);
  }
</style>
