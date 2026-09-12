<script lang="ts">
  import { enhance } from "$app/forms";
  import { resolve } from "$app/paths";
  import CarriedLink from "$lib/components/content/CarriedLink.svelte";
  import ContentLanguageNotice from "$lib/components/content/ContentLanguageNotice.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import {
    acceptAttribute,
    MAX_UPLOAD_BYTES,
    type UploadRejection,
  } from "$lib/content/upload";
  import { languageParams } from "$lib/content/language";
  import { m } from "$lib/paraglide/messages.js";
  import type { ActionData, PageData } from "./$types";

  type Props = {
    data: PageData;
    form: ActionData;
  };

  let { data, form }: Props = $props();

  /**
   * Only ever true after `use:enhance` has taken the submit over.
   *
   * A plain form post navigates away, so this never gets a chance to be shown
   * — which is the point: the progress affordance is the enhancement, and the
   * base workflow does not depend on it.
   */
  let uploading = $state(false);

  const sourcesPath = resolve("/content/sources", {});
  const catalogPath = resolve("/content", {});
  const maxMegabytes = Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024));

  /** The only state this page carries onward is the content language. */
  const languageOnly = $derived(languageParams(data.contentLanguage.override));

  const rejection = $derived(
    form && "rejection" in form ? (form.rejection as UploadRejection) : null,
  );
  const accepted = $derived(
    form && "accepted" in form ? form.accepted : null,
  );
  const rejectionMessage = $derived(
    rejection === null ? null : rejectionText(rejection),
  );

  function rejectionText(reason: UploadRejection): string {
    switch (reason) {
      case "title_required":
        return m.content_upload_error_title_required();
      case "title_too_long":
        return m.content_upload_error_title_too_long();
      case "file_required":
        return m.content_upload_error_file_required();
      case "empty_file":
        return m.content_upload_error_empty();
      case "too_large":
        return m.content_upload_error_too_large({ megabytes: maxMegabytes });
      case "unsupported_type":
        return m.content_upload_error_unsupported({
          formats: acceptAttribute(),
        });
      case "content_mismatch":
        return m.content_upload_error_mismatch();
      default:
        return m.content_upload_error_failed();
    }
  }
</script>

<PageHeader
  heading={m.content_sources_heading()}
  summary={m.content_sources_summary()}
/>

<ContentLanguageNotice
  action={sourcesPath}
  params={languageOnly}
  state={data.contentLanguage}
  uiLocale={data.uiLocale}
/>

<section class="upload" aria-labelledby="content-upload-heading">
  <h2 id="content-upload-heading">{m.content_upload_heading()}</h2>
  <p class="lead">{m.content_upload_body()}</p>

  <!--
    `enctype` and a POST are all this needs to work. `use:enhance` only keeps
    the learner on the page and turns the button into a progress state; with
    JavaScript unavailable the browser posts the same body to the same action
    and the page re-renders with the result.
  -->
  <form
    method="POST"
    action="?/upload"
    enctype="multipart/form-data"
    use:enhance={() => {
      uploading = true;
      return async ({ update }) => {
        await update();
        uploading = false;
      };
    }}
  >
    <div class="field">
      <label for="upload-title">{m.content_upload_title_label()}</label>
      <input
        id="upload-title"
        name="title"
        type="text"
        required
        maxlength="200"
        value={form && "title" in form ? String(form.title ?? "") : ""}
      />
    </div>

    <div class="field">
      <label for="upload-file">{m.content_upload_file_label()}</label>
      <p id="upload-file-hint" class="hint">
        {m.content_upload_file_hint({
          formats: acceptAttribute(),
          megabytes: maxMegabytes,
        })}
      </p>
      <input
        id="upload-file"
        name="file"
        type="file"
        required
        accept={acceptAttribute()}
        aria-describedby="upload-file-hint"
      />
    </div>

    <button type="submit" disabled={uploading}>
      {uploading ? m.content_upload_in_progress() : m.content_upload_submit()}
    </button>
  </form>

  {#if rejectionMessage}
    <p class="error" role="alert">{rejectionMessage}</p>
  {/if}

  {#if accepted}
    <p class="accepted" role="status">
      {m.content_upload_accepted({ title: accepted.title })}
    </p>
    <p class="accepted-state">
      {m.content_upload_state_queued()}
    </p>
  {/if}
</section>

<PanelSection
  id="content-known-sources"
  heading={m.content_sources_known_heading()}
  status={data.sources.status}
  isEmpty={data.sources.data.length === 0}
>
  {#snippet empty()}
    <div class="empty-state">
      <p class="empty-title">{m.content_sources_empty_title()}</p>
      <p class="empty-body">{m.content_sources_empty_body()}</p>
    </div>
  {/snippet}

  <ul class="sources">
    {#each data.sources.data as source (source.id)}
      <li>
        <span>{source.title || m.content_source_untitled()}</span>
        <span class="ref">{source.external_ref}</span>
      </li>
    {/each}
  </ul>
</PanelSection>

<form class="discover" method="POST" action="?/discover" use:enhance>
  <button type="submit">{m.content_sources_discover()}</button>
  {#if form && "discoverFailed" in form}
    <p class="error" role="alert">{m.content_sources_discover_failed()}</p>
  {/if}
</form>

<div class="catalog-link">
  <CarriedLink
    action={catalogPath}
    label={m.content_back_to_catalog()}
    params={languageOnly}
  />
</div>

<style>
  .upload {
    display: grid;
    min-width: 0;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  h2 {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  form {
    display: grid;
    min-width: 0;
    gap: 0.75rem;
  }

  .field {
    display: grid;
    min-width: 0;
    gap: 0.25rem;
  }

  label {
    overflow-wrap: anywhere;
  }

  .hint,
  .lead,
  .empty-body,
  .ref {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  input {
    min-height: 2.75rem;
    min-width: 0;
    width: 100%;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.7rem;
  }

  button {
    min-height: 2.75rem;
    min-width: 2.75rem;
    justify-self: start;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    padding: 0.55rem 0.9rem;
    overflow-wrap: anywhere;
  }

  .error,
  .accepted,
  .accepted-state,
  .empty-title {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .error {
    color: var(--danger);
  }

  .accepted-state {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .empty-title {
    font-weight: 600;
  }

  .empty-state {
    display: grid;
    min-width: 0;
    gap: 0.35rem;
  }

  .sources {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .sources li {
    display: flex;
    min-width: 0;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
    border-top: 1px solid var(--border);
    padding-top: 0.4rem;
    overflow-wrap: anywhere;
  }

  .discover {
    margin-top: 1rem;
  }

  .catalog-link {
    margin-top: 1rem;
  }

  @media (max-width: 560px) {
    .sources li {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.15rem;
    }
  }
</style>
