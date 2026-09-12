<script lang="ts">
  import { resolve } from "$app/paths";
  import CarriedLink from "$lib/components/content/CarriedLink.svelte";
  import ContentLanguageNotice from "$lib/components/content/ContentLanguageNotice.svelte";
  import FilterDrawer from "$lib/components/content/FilterDrawer.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import {
    CONTENT_STATUSES,
    contentParams,
    isContentItemReady,
    type ContentItem,
  } from "$lib/content/filters";
  import { languageParams } from "$lib/content/language";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const listPath = resolve("/content", {});
  const setupPath = resolve("/content/sources", {});

  const params = $derived(
    contentParams(data.filters, data.contentLanguage.override),
  );
  /** Only the content language travels to another page; filters do not. */
  const languageOnly = $derived(languageParams(data.contentLanguage.override));

  const visibleCount = $derived(
    data.groups.reduce((total, group) => total + group.items.length, 0),
  );
  const filtersActive = $derived(
    data.filters.query !== "" || data.filters.status !== "all",
  );

  const catalogNote = $derived.by(() => {
    if (data.unlistedSourceCount > 0) {
      return m.content_catalog_truncated({ count: data.unlistedSourceCount });
    }
    return data.groups.length > 0
      ? m.content_catalog_count({ count: visibleCount })
      : undefined;
  });

  const statusLabels = {
    all: m.content_status_all,
    pending: m.content_status_pending,
    ready: m.content_status_ready,
  } as const;

  /** The stage a content item is waiting on, or that it has finished them all. */
  function stageLabel(item: ContentItem): string {
    if (isContentItemReady(item)) {
      return m.content_stage_ready();
    }
    if (item.download_status !== "completed") {
      return m.content_stage_downloading();
    }
    if (item.transcription_status !== "completed") {
      return m.content_stage_transcribing();
    }
    return m.content_stage_indexing();
  }
</script>

<PageHeader heading={m.content_heading()} summary={m.content_summary()} />

<ContentLanguageNotice
  action={listPath}
  {params}
  state={data.contentLanguage}
  uiLocale={data.uiLocale}
/>

<FilterDrawer action={listPath} open={data.drawerOpen} {params}>
  {#snippet fields()}
    <div class="field">
      <label for="content-query">{m.content_filter_query()}</label>
      <input
        id="content-query"
        name="q"
        type="search"
        value={data.filters.query}
        autocomplete="off"
      />
    </div>
    <div class="field">
      <label for="content-status">{m.content_filter_status()}</label>
      <select id="content-status" name="status" value={data.filters.status}>
        {#each CONTENT_STATUSES as status (status)}
          <option value={status} selected={status === data.filters.status}>
            {statusLabels[status]()}
          </option>
        {/each}
      </select>
    </div>
  {/snippet}
</FilterDrawer>

<PanelSection
  id="content-catalog"
  heading={m.content_catalog_heading()}
  status={data.sources.status}
  isEmpty={data.groups.length === 0}
  note={catalogNote}
>
  {#snippet empty()}
    <div class="empty-state">
      {#if filtersActive}
        <p class="empty-title">{m.content_no_matches_title()}</p>
        <p class="empty-body">{m.content_no_matches_body()}</p>
        <a href={listPath}>{m.content_filters_reset()}</a>
      {:else}
        <p class="empty-title">{m.content_empty_title()}</p>
        <p class="empty-body">{m.content_empty_body()}</p>
        <CarriedLink
          action={setupPath}
          label={m.content_open_sources()}
          params={languageOnly}
          primary
        />
      {/if}
    </div>
  {/snippet}

  <div class="groups">
    {#each data.groups as group (group.source.id)}
      <article class="group" aria-labelledby={`source-${group.source.id}`}>
        <header>
          <h3 id={`source-${group.source.id}`}>
            {group.source.title || m.content_source_untitled()}
          </h3>
          <p>
            {m.content_group_summary({
              ready: group.readyCount,
              total: group.items.length,
            })}
          </p>
        </header>

        <ul>
          {#each group.items as item (item.id)}
            <li>
              <span class="item-title">
                {#if item.sequence_number}<span class="sequence"
                    >#{item.sequence_number}</span
                  >{/if}
                {item.title}
              </span>
              <span
                class="stage"
                class:ready={isContentItemReady(item)}
                data-state={isContentItemReady(item) ? "ready" : "pending"}
              >
                {stageLabel(item)}
              </span>
            </li>
          {/each}
        </ul>
      </article>
    {/each}
  </div>
</PanelSection>

<div class="setup-link">
  <CarriedLink
    action={setupPath}
    label={m.content_open_sources()}
    params={languageOnly}
  />
</div>

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

  .groups {
    display: grid;
    min-width: 0;
    gap: 0.9rem;
  }

  .group {
    display: grid;
    min-width: 0;
    gap: 0.6rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.8rem;
  }

  .group header {
    display: grid;
    min-width: 0;
    gap: 0.15rem;
  }

  h3 {
    margin: 0;
    font-size: 0.98rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .group header p,
  .empty-title,
  .empty-body {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .group header p,
  .empty-body {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .empty-title {
    font-weight: 600;
  }

  ul {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    border-top: 1px solid var(--border);
    padding-top: 0.4rem;
  }

  .item-title {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .sequence {
    color: var(--muted);
  }

  .stage {
    flex: 0 0 auto;
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    color: var(--muted);
    padding: 0.15rem 0.6rem;
    font-size: 0.78rem;
    overflow-wrap: anywhere;
  }

  .stage.ready {
    border-color: var(--accent-strong);
    color: var(--accent-strong);
  }

  .empty-state {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.35rem;
  }

  .empty-state a {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    overflow-wrap: anywhere;
  }

  .setup-link {
    margin-top: 1rem;
  }

  @media (max-width: 560px) {
    li {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.25rem;
    }
  }
</style>
