<script lang="ts">
  import { enhance } from "$app/forms";
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import CarriedLink from "$lib/components/content/CarriedLink.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import type { ActionData, PageData } from "./$types";

  type Props = {
    data: PageData;
    form: ActionData;
  };

  let { data, form }: Props = $props();

  const studyPath = resolve("/study", {});
  const syncPath = resolve("/content/sources", {});

  const errorMessage = $derived(errorText(form?.error));

  function errorText(code: string | undefined): string | null {
    switch (code) {
      case "study.topic_required":
        return m.study_topic_required();
      case "study.learning_path_required":
        return m.study_path_required();
      case "study.learning_path_select_failed":
        return m.study_path_select_failed();
      case "study.session_start_failed":
        return m.study_session_start_failed();
      default:
        return code ? m.study_not_available() : null;
    }
  }
</script>

<PageHeader heading={m.study_heading()} summary={m.study_summary()} />

{#if data.learningPaths !== null}
  <section class="picker" aria-labelledby="study-path-heading">
    <h2 id="study-path-heading">{m.study_path_heading()}</h2>
    {#if data.learningPaths.status !== "ready"}
      <p class="notice" role="status">{m.study_path_unavailable()}</p>
    {:else if data.learningPaths.data.length === 0}
      <div class="empty-state">
        <p class="empty-title">{m.study_path_empty_title()}</p>
        <p class="notice">{m.study_path_empty_body()}</p>
        <CarriedLink action={syncPath} label={m.study_path_open_sync()} primary />
      </div>
    {:else}
      <p class="notice">{m.study_path_summary()}</p>
      <form method="POST" action="?/select" use:enhance>
        <fieldset>
          <legend>{m.study_path_legend()}</legend>
          {#each data.learningPaths.data as path (path.id)}
            <label class="path-option">
              <input
                type="radio"
                name="learning_path_id"
                value={path.id}
                checked={path.id === data.learningPathId}
                required
              />
              <span class="session-copy">
                <strong>{path.title}</strong>
                <span>{path.short_title}</span>
              </span>
            </label>
          {/each}
        </fieldset>
        <button type="submit">{m.study_path_select()}</button>
      </form>
    {/if}
    {#if errorMessage}
      <p class="error" role="alert">{errorMessage}</p>
    {/if}
    {#if data.learningPathId !== null}
      <a href={studyPath}>{m.study_path_keep()}</a>
    {/if}
  </section>
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

  <div class="change-path">
    <CarriedLink
      action={studyPath}
      label={m.study_path_change()}
      params={{ choose: "1" }}
    />
  </div>

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
  .picker,
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

  label,
  legend,
  .empty-title {
    font-weight: 700;
  }

  fieldset {
    display: grid;
    gap: 0.4rem;
    margin: 0;
    border: 0;
    padding: 0;
  }

  .path-option {
    display: flex;
    min-height: 2.75rem;
    align-items: center;
    gap: 0.6rem;
    border-top: 1px solid var(--border);
    padding-top: 0.4rem;
    font-weight: 400;
  }

  .path-option input {
    min-height: auto;
    padding: 0;
  }

  .empty-state {
    display: grid;
    gap: 0.5rem;
  }

  .empty-title {
    margin: 0;
  }

  .change-path {
    margin-bottom: 0.75rem;
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
