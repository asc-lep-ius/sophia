<script lang="ts">
  import { resolve } from "$app/paths";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import { searchContent } from "$lib/api/search";
  import { SearchController } from "$lib/search/controller.svelte";
  import {
    QUERY_PARAM,
    SEARCH_SOURCE_FILTERS,
    SOURCE_FILTER_PARAM,
    SOURCE_PARAM,
    formatTimestamp,
    scoreBand,
    type SearchResult,
  } from "$lib/search/results";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const searchPath = resolve("/search", {});
  const sourcesPath = resolve("/content/sources", {});

  const kindLabels = {
    all: m.search_kind_all,
    transcript: m.search_kind_transcript,
    document: m.search_kind_document,
  } as const;

  const bandLabels = {
    strong: m.search_score_strong,
    moderate: m.search_score_moderate,
    weak: m.search_score_weak,
  } as const;

  /**
   * The retrieval prompts the legacy page cycled through, in Bloom order.
   *
   * Reading a passage you searched for feels like learning and mostly is not;
   * writing something from it before moving on is the part that sticks. The
   * legacy page also locked the other results until the prompt was answered.
   * That is deliberately not reproduced: a surface that traps a learner behind
   * a textarea they cannot skip is a dark pattern, and nothing in #101 asks
   * for it. The prompt is offered, and it advances when it is answered.
   */
  const retrievalPrompts = [
    m.search_prompt_list,
    m.search_prompt_explain,
    m.search_prompt_example,
    m.search_prompt_connect,
    m.search_prompt_assumptions,
    m.search_prompt_question,
  ];

  let selected = $state<string | null>(null);
  let retrieval = $state("");
  let retrievalLevel = $state(0);
  let retrievalMissing = $state(false);
  /** Whether the learner has typed since this page load answered a query. */
  let typed = $state(false);

  // Seeded from the server render so a hydrating page does not immediately
  // repeat the search it was just given the answer to.
  const controller = new SearchController({
    run: (query, signal) =>
      searchContent(
        {
          contentSourceId: data.selectedSourceId ?? 0,
          csrfToken: data.csrfToken ?? "",
          learningPathId: data.learningPathId ?? 0,
        },
        { query, sourceFilter: data.sourceFilter },
        signal,
      ),
  });

  /**
   * Which answer is on screen: the one this page load carried, or the live one.
   *
   * The server already answered `?q=`, so a freshly loaded page shows that and
   * runs nothing. The first keystroke hands the display to the controller and
   * it keeps it until the next navigation, which is what stops a cleared input
   * from falling back to a result set for a query nobody is looking at.
   */
  const hasServerAnswer = $derived(!typed && data.results !== null);
  /**
   * Four states, not three: a scope the learner does not have is kept apart
   * from a service that did not answer, the same way every panel on this
   * surface keeps them apart. Collapsing them tells someone reading another
   * tenant's course to try again, which will never work.
   */
  const status = $derived(
    hasServerAnswer ? (data.results?.status ?? "error") : controller.status,
  );
  const results = $derived(
    hasServerAnswer ? (data.results?.data ?? []) : controller.results,
  );
  const answeredQuery = $derived(
    hasServerAnswer ? data.query : controller.submitted,
  );
  const navigationKey = $derived(
    `${data.query}|${data.selectedSourceId}|${data.sourceFilter}`,
  );
  const selectedResult = $derived(
    results.find((result) => result.content_item_id === selected) ?? null,
  );
  const searchable = $derived(
    data.selectedSourceId !== null && data.learningPathId !== null,
  );

  // A navigation carries a fresh server answer, so the live one is retired.
  $effect(() => {
    void navigationKey;
    typed = false;
    selected = null;
    controller.setQuery("");
  });

  $effect(() => () => controller.dispose());

  /**
   * Typing searches; submitting is what puts the query in the URL.
   *
   * The form around the input is a GET form, so pressing Enter or the search
   * button navigates to `?q=` and the server answers it — which is what makes
   * a search shareable, reloadable and reachable with no JavaScript at all.
   * Rewriting the address bar on every keystroke instead was tried and
   * dropped: it needs `replaceState` with a hand-built URL, which is the
   * pattern `svelte/no-navigation-without-resolve` exists to refuse, and it
   * buys only that a half-typed word survives a reload.
   */
  function onQueryInput(event: Event): void {
    const value = (event.currentTarget as HTMLInputElement).value;
    typed = true;
    selected = null;
    controller.setQuery(value);
  }

  function toggleResult(result: SearchResult): void {
    selected = selected === result.content_item_id ? null : result.content_item_id;
    retrieval = "";
    retrievalMissing = false;
  }

  function submitRetrieval(event: Event): void {
    event.preventDefault();
    if (retrieval.trim() === "") {
      retrievalMissing = true;
      return;
    }
    retrievalMissing = false;
    retrieval = "";
    retrievalLevel = (retrievalLevel + 1) % retrievalPrompts.length;
    selected = null;
  }

  function statusText(): string {
    if (!searchable) {
      return m.search_no_sources_body();
    }
    if (status === "loading") {
      return m.search_status_loading();
    }
    if (status === "unauthorized") {
      return m.dashboard_panel_unauthorized();
    }
    if (status === "error") {
      return m.search_status_error();
    }
    if (answeredQuery === "") {
      return m.search_status_idle();
    }
    return results.length === 0
      ? m.search_no_results({ query: answeredQuery })
      : m.search_results_count({ count: results.length });
  }
</script>

<PageHeader heading={m.search_heading()} summary={m.search_summary()} />

{#if data.sources.status !== "ready" && data.sources.data.length === 0}
  <p class="notice error" role="status">{m.dashboard_panel_error()}</p>
{:else if !searchable}
  <section class="empty-state" aria-labelledby="search-empty-heading">
    <h2 id="search-empty-heading">{m.search_no_sources_title()}</h2>
    <p>{m.search_no_sources_body()}</p>
    <a class="primary" href={sourcesPath}>{m.search_open_sources()}</a>
  </section>
{:else}
  <!--
    A GET form, so a submitted query is a URL the server can answer. Typing
    searches without submitting; pressing Enter or arriving from a shared link
    goes through here instead, and both end up showing the same results.
  -->
  <form class="search-form" method="get" action={searchPath}>
    <div class="field query">
      <label for="search-query">{m.search_query_label()}</label>
      <input
        id="search-query"
        name={QUERY_PARAM}
        type="search"
        autocomplete="off"
        value={data.query}
        placeholder={m.search_query_placeholder()}
        oninput={onQueryInput}
      />
    </div>

    <div class="field">
      <label for="search-source">{m.search_source_label()}</label>
      <select id="search-source" name={SOURCE_PARAM}>
        {#each data.sources.data as source (source.id)}
          <option value={source.id} selected={source.id === data.selectedSourceId}>
            {source.title}
          </option>
        {/each}
      </select>
    </div>

    <div class="field">
      <label for="search-kind">{m.search_kind_label()}</label>
      <select id="search-kind" name={SOURCE_FILTER_PARAM}>
        {#each SEARCH_SOURCE_FILTERS as kind (kind)}
          <option value={kind} selected={kind === data.sourceFilter}>
            {kindLabels[kind]()}
          </option>
        {/each}
      </select>
    </div>

    <button type="submit">{m.search_submit()}</button>
  </form>

  <p class="search-status" role="status" aria-live="polite">{statusText()}</p>

  <PanelSection
    id="search-results"
    heading={m.search_results_heading()}
    status={status === "error" || status === "unauthorized" ? status : "ready"}
    isEmpty={results.length === 0}
  >
    {#snippet empty()}
      <p class="empty-body">
        {answeredQuery === ""
          ? m.search_status_idle()
          : m.search_no_results({ query: answeredQuery })}
      </p>
    {/snippet}

    <ul class="results">
      {#each results as result (result.content_item_id)}
        {@const band = scoreBand(result.score)}
        <li class="result" class:selected={selected === result.content_item_id}>
          <div class="result-head">
            <h3>{result.title}</h3>
            <span class="band" data-band={band}>{bandLabels[band]()}</span>
          </div>
          <p class="meta">
            <span
              >{m.search_timespan({
                end: formatTimestamp(result.end_time),
                start: formatTimestamp(result.start_time),
              })}</span
            >
            <span class="source">{result.source}</span>
          </p>
          <p class="preview">{result.chunk_text}</p>
          <button
            type="button"
            aria-expanded={selected === result.content_item_id}
            onclick={() => toggleResult(result)}
          >
            {selected === result.content_item_id
              ? m.search_close_result()
              : m.search_open_result()}
          </button>
        </li>
      {/each}
    </ul>
  </PanelSection>

  {#if selectedResult}
    <section class="retrieval" aria-labelledby="retrieval-heading">
      <h2 id="retrieval-heading">{m.search_retrieval_heading()}</h2>
      <p class="hint">{m.search_retrieval_hint()}</p>
      <p class="prompt">{retrievalPrompts[retrievalLevel]?.()}</p>
      <form onsubmit={submitRetrieval}>
        <label for="retrieval-response">{m.search_retrieval_label()}</label>
        <textarea
          id="retrieval-response"
          rows="4"
          bind:value={retrieval}
          aria-describedby={retrievalMissing ? "retrieval-error" : undefined}
        ></textarea>
        {#if retrievalMissing}
          <p id="retrieval-error" class="error" role="alert">
            {m.search_retrieval_required()}
          </p>
        {/if}
        <button type="submit">{m.search_retrieval_submit()}</button>
      </form>
    </section>
  {/if}
{/if}

<style>
  .search-form {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    align-items: end;
    gap: 0.75rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 0.9rem;
    margin-bottom: 1rem;
  }

  .field {
    display: grid;
    min-width: 0;
    gap: 0.25rem;
  }

  .field.query {
    grid-column: 1 / -1;
  }

  label {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  input,
  select,
  textarea {
    min-height: 2.75rem;
    min-width: 0;
    width: 100%;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.7rem;
    font: inherit;
  }

  textarea {
    min-height: 5rem;
  }

  button {
    display: inline-flex;
    min-height: 2.75rem;
    min-width: 2.75rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.8rem;
    font: inherit;
    overflow-wrap: anywhere;
    cursor: pointer;
  }

  .search-status,
  .notice,
  .empty-body {
    margin: 0 0 0.75rem;
    color: var(--muted);
    overflow-wrap: anywhere;
  }

  .notice.error,
  .error {
    color: var(--danger);
  }

  .results {
    display: grid;
    min-width: 0;
    gap: 0.75rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .result {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.4rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-raised);
    padding: 0.8rem;
  }

  .result.selected {
    border-color: var(--accent-strong);
  }

  .result-head {
    display: flex;
    min-width: 0;
    width: 100%;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
  }

  h2,
  h3 {
    margin: 0;
    font-size: 1rem;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  .band {
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-size: 0.78rem;
  }

  .band[data-band="strong"] {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  .meta {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .preview {
    margin: 0;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }

  .empty-state,
  .retrieval {
    display: grid;
    max-width: 52rem;
    min-width: 0;
    justify-items: start;
    gap: 0.6rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
    margin-top: 1rem;
  }

  .retrieval form {
    display: grid;
    min-width: 0;
    width: 100%;
    justify-items: start;
    gap: 0.4rem;
  }

  .hint,
  .prompt {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .hint {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .prompt {
    font-style: italic;
  }

  a.primary {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    padding: 0.5rem 0.9rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }

  @media (max-width: 720px) {
    .search-form {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
