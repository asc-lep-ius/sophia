<script lang="ts">
  import { LANGUAGE_PARAM } from "$lib/content/language";
  import { m } from "$lib/paraglide/messages.js";
  import CarriedParams from "./CarriedParams.svelte";
  import type { ContentLanguageState } from "$lib/content/language";
  import type { Locale } from "$lib/i18n/locale";

  type Props = {
    /** Already-resolved path of the page the switch returns to. */
    action: string;
    /** Filters to keep when the content language changes. */
    params?: Record<string, string>;
    state: ContentLanguageState;
    uiLocale: Locale;
  };

  let { action, params = {}, state, uiLocale }: Props = $props();

  const languageNames = { de: "Deutsch", en: "English" } as const;

  const reason = $derived.by(() => {
    if (state.origin === "override") {
      return m.content_language_from_override();
    }
    if (state.origin === "learning_path") {
      return m.content_language_from_learning_path();
    }
    return m.content_language_from_default();
  });

  const other = $derived(state.language === "de" ? "en" : "de");
</script>

<!--
  Says both languages, always, and never merges them.

  A German course read through an English interface is the ordinary case here.
  Showing only one of the two would leave the learner unable to tell whether
  the German in front of them is the material or a mis-set preference — and
  the UI locale is never allowed to be what answers that question.
-->
<aside class="language-notice" aria-label={m.content_language_label()}>
  <dl>
    <div>
      <dt>{m.content_language_content()}</dt>
      <dd lang={state.language}>{languageNames[state.language]}</dd>
    </div>
    <div>
      <dt>{m.content_language_interface()}</dt>
      <dd lang={uiLocale}>{languageNames[uiLocale]}</dd>
    </div>
  </dl>
  <p>{reason}</p>

  <form method="get" {action}>
    <CarriedParams {params} omit={LANGUAGE_PARAM} />
    <button type="submit" name={LANGUAGE_PARAM} value={other}>
      {m.content_language_switch({ language: languageNames[other] })}
    </button>
  </form>
</aside>

<style>
  .language-notice {
    display: grid;
    min-width: 0;
    gap: 0.5rem;
    margin-bottom: 1rem;
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent-strong);
    border-radius: 8px;
    background: var(--surface);
    padding: 0.8rem 0.9rem;
  }

  dl {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.35rem 1.5rem;
    margin: 0;
  }

  dl div {
    display: grid;
    min-width: 0;
    gap: 0.1rem;
  }

  dt,
  p {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  dd {
    margin: 0;
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  button {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    border: none;
    background: none;
    color: var(--accent-strong);
    padding: 0.4rem 0;
    font: inherit;
    text-align: start;
    text-decoration: underline;
    overflow-wrap: anywhere;
    cursor: pointer;
  }
</style>
