<script lang="ts">
  import { resolve } from "$app/paths";
  import CarriedLink from "$lib/components/content/CarriedLink.svelte";
  import ContentLanguageNotice from "$lib/components/content/ContentLanguageNotice.svelte";
  import FilterDrawer from "$lib/components/content/FilterDrawer.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import {
    topicParams,
    TOPIC_ORIGINS,
    TOPIC_RATINGS,
    type TopicRow,
  } from "$lib/content/filters";
  import { languageParams } from "$lib/content/language";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const listPath = resolve("/topics", {});
  const quickstartPath = resolve("/quickstart", {});

  const params = $derived(
    topicParams(data.filters, data.contentLanguage.override),
  );
  /** Only the content language travels to another page; filters do not. */
  const languageOnly = $derived(languageParams(data.contentLanguage.override));

  const filtersActive = $derived(
    data.filters.query !== "" ||
      data.filters.origin !== "all" ||
      data.filters.rated !== "all",
  );

  const originLabels = {
    all: m.topics_origin_all,
    transcript: m.topics_origin_transcript,
    quiz: m.topics_origin_quiz,
    manual: m.topics_origin_manual,
  } as const;

  const ratingLabels = {
    all: m.topics_rated_all,
    rated: m.topics_rated_yes,
    unrated: m.topics_rated_no,
  } as const;

  /** The prediction as a percentage, or a plain "not rated" when there is none. */
  function confidenceLabel(row: TopicRow): string {
    if (row.confidence === null) {
      return m.topics_confidence_unrated();
    }
    return m.topics_confidence_predicted({
      percent: Math.round(row.confidence.predicted * 100),
    });
  }
</script>

<PageHeader heading={m.topics_heading()} summary={m.topics_summary()} />

<ContentLanguageNotice
  action={listPath}
  {params}
  state={data.contentLanguage}
  uiLocale={data.uiLocale}
/>

{#if data.learningPathId === null}
  <p class="notice">{m.dashboard_no_learning_path()}</p>
{:else}
  <FilterDrawer action={listPath} open={data.drawerOpen} {params}>
    {#snippet fields()}
      <div class="field">
        <label for="topic-query">{m.topics_filter_query()}</label>
        <input
          id="topic-query"
          name="q"
          type="search"
          value={data.filters.query}
          autocomplete="off"
        />
      </div>
      <div class="field">
        <label for="topic-origin">{m.topics_filter_origin()}</label>
        <select id="topic-origin" name="origin" value={data.filters.origin}>
          {#each TOPIC_ORIGINS as origin (origin)}
            <option value={origin} selected={origin === data.filters.origin}>
              {originLabels[origin]()}
            </option>
          {/each}
        </select>
      </div>
      <div class="field">
        <label for="topic-rated">{m.topics_filter_rated()}</label>
        <select id="topic-rated" name="rated" value={data.filters.rated}>
          {#each TOPIC_RATINGS as rated (rated)}
            <option value={rated} selected={rated === data.filters.rated}>
              {ratingLabels[rated]()}
            </option>
          {/each}
        </select>
      </div>
    {/snippet}
  </FilterDrawer>

  <PanelSection
    id="topics-list"
    heading={m.topics_list_heading()}
    status={data.rows.status}
    isEmpty={data.rows.data.length === 0}
    note={m.topics_list_count({
      shown: data.rows.data.length,
      total: data.totalCount,
    })}
  >
    {#snippet empty()}
      <div class="empty-state">
        {#if filtersActive}
          <p class="empty-title">{m.topics_no_matches_title()}</p>
          <p class="empty-body">{m.topics_no_matches_body()}</p>
          <a href={listPath}>{m.content_filters_reset()}</a>
        {:else}
          <p class="empty-title">{m.topics_empty_title()}</p>
          <p class="empty-body">{m.topics_empty_body()}</p>
          <CarriedLink
            action={quickstartPath}
            label={m.topics_open_quickstart()}
            params={languageOnly}
            primary
          />
        {/if}
      </div>
    {/snippet}

    <ul class="topics">
      {#each data.rows.data as row (row.topic.topic)}
        <li>
          <span class="topic" lang={data.contentLanguage.language}
            >{row.topic.topic}</span
          >
          <span class="meta">
            <span class="origin">{originLabels[row.topic.source]()}</span>
            <span class="confidence" class:unrated={row.confidence === null}>
              {confidenceLabel(row)}
            </span>
          </span>
        </li>
      {/each}
    </ul>
  </PanelSection>
{/if}

<style>
  .field {
    display: grid;
    min-width: 0;
    gap: 0.25rem;
  }

  .field label {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .field input,
  .field select {
    min-height: 2.75rem;
    min-width: 0;
    width: 100%;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.7rem;
  }

  .topics {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .topics li {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    border-top: 1px solid var(--border);
    padding-top: 0.45rem;
  }

  .topic {
    min-width: 0;
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  .meta {
    display: flex;
    flex: 0 0 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
  }

  .origin,
  .confidence {
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    padding: 0.15rem 0.6rem;
    font-size: 0.78rem;
    overflow-wrap: anywhere;
  }

  .confidence {
    border-color: var(--accent-strong);
    color: var(--accent-strong);
  }

  .confidence.unrated {
    border-color: var(--border-strong);
    color: var(--muted);
  }

  .notice,
  .empty-title,
  .empty-body {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .empty-body {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .empty-title {
    font-weight: 600;
  }

  .empty-state {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.35rem;
  }

  .empty-state a {
    min-height: 2.75rem;
    display: inline-flex;
    align-items: center;
    overflow-wrap: anywhere;
  }

  @media (max-width: 560px) {
    .topics li {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.3rem;
    }
  }
</style>
