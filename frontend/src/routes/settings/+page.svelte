<script lang="ts">
  import { enhance } from "$app/forms";
  import { invalidateAll } from "$app/navigation";
  import { page } from "$app/state";
  import type { ActionResult } from "@sveltejs/kit";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { normalizeLocale, type Locale } from "$lib/i18n/locale";
  import { m } from "$lib/paraglide/messages.js";
  import { serialiseSubmissions } from "$lib/settings/serialSubmit";
  import { applyThemeToDocument, normalizeTheme, type Theme } from "$lib/theme";

  type SettingsState = {
    locale: string;
    theme: string;
  };

  type SettingsPageData = {
    locale: string;
    settings?: SettingsState | null;
    theme: Theme;
  };

  type SettingsForm = {
    error?: "save_failed";
    settings?: SettingsState;
  };

  type Choice = { locale?: Locale; theme?: Theme };
  type Outcome = "failed" | "saved";

  let {
    data = pageDataFallback(),
    form,
  }: { data?: SettingsPageData; form?: SettingsForm } = $props();

  const themes = [
    { label: m.settings_theme_light, value: "light" },
    { label: m.settings_theme_dark, value: "dark" },
    { label: m.settings_theme_oled, value: "oled" },
  ] satisfies { label: () => string; value: Theme }[];

  const localeOptions = [
    { label: m.settings_locale_english, value: "en" },
    { label: m.settings_locale_german, value: "de" },
  ] satisfies { label: () => string; value: Locale }[];

  const settings = $derived(
    form?.settings ?? data.settings ?? fallbackSettings(data),
  );
  const persistedTheme = $derived(normalizeTheme(settings.theme));

  /**
   * The language on the page, not the one on the session record. The two are
   * separate sources of truth and the Paraglide cookie wins
   * (docs/frontend-paraglide-decision.md), so anchoring the highlight to the
   * record would leave it pointing at a language the learner is not reading.
   */
  const renderedLocale = $derived(normalizeLocale(data.locale) ?? "en");

  /**
   * Clicks the server has not answered yet. They sit on top of the persisted
   * values rather than overwriting them, so a refused save falls back to what
   * the session holds by clearing this, not by remembering what to restore.
   */
  let choice = $state<Choice>({});
  let saving = $state(false);
  /** How the last enhanced save ended; `form` only ever answers a plain post. */
  let outcome = $state<Outcome | null>(null);
  /** Bumped on every click, so settling an older save cannot clear a newer one. */
  let revision = 0;

  const selectedTheme = $derived(choice.theme ?? persistedTheme);
  const selectedLocale = $derived(choice.locale ?? renderedLocale);
  const shownOutcome = $derived<Outcome | null>(
    saving ? null : (outcome ?? formOutcome(form)),
  );

  // The page is painted in whatever the control shows, pending or saved. The
  // cookie behind the next page load is the action's to write, once the
  // session has taken the value.
  $effect(() => {
    applyThemeToDocument(selectedTheme);
  });

  /** The one way any control applies: record the click, submit the form. */
  function choose(change: Choice, control: HTMLInputElement) {
    choice = { ...choice, ...change };
    revision += 1;
    saving = true;
    control.form?.requestSubmit();
  }

  const saveOnChange = serialiseSubmissions(settle);

  async function settle(result: ActionResult) {
    // Paraglide resolves a page's language once per document load, so a new
    // language needs a new document rather than a client-side navigation.
    if (result.type === "redirect") {
      window.location.assign(result.location);
      return;
    }
    if (languageChanged(result)) {
      window.location.reload();
      return;
    }

    const settled = revision;
    outcome = result.type === "success" ? "saved" : "failed";
    // On a refusal as well: an earlier save in the same chain may have landed,
    // and the controls fall back to whatever the session now holds.
    await invalidateAll();
    if (settled === revision) {
      choice = {};
      saving = false;
    }
  }

  /** A chain whose first save switched the language can end in a plain success. */
  function languageChanged(result: ActionResult): boolean {
    const saved =
      result.type === "success"
        ? (result.data as SettingsForm | undefined)?.settings
        : undefined;
    return saved !== undefined && normalizeLocale(saved.locale) !== renderedLocale;
  }

  function formOutcome(submitted: SettingsForm | undefined): Outcome | null {
    if (submitted?.error) {
      return "failed";
    }
    return submitted?.settings ? "saved" : null;
  }

  function fallbackSettings(pageData: SettingsPageData): SettingsState {
    return {
      locale: pageData.locale,
      theme: pageData.theme,
    };
  }

  function pageDataFallback(): SettingsPageData {
    const pageData = page.data as Partial<SettingsPageData>;
    return {
      locale: typeof pageData.locale === "string" ? pageData.locale : "en",
      settings: pageData.settings ?? null,
      theme: normalizeTheme(
        typeof pageData.theme === "string" ? pageData.theme : undefined,
      ),
    };
  }
</script>

<PageHeader heading={m.settings_heading()} summary={m.settings_summary()} />

<!--
  Every control saves itself: a change submits this form, one save at a time.
  Without JavaScript nothing listens for the change, so the <noscript> button
  posts the same form to the same action.
-->
<form
  class="settings-panel"
  method="POST"
  aria-labelledby="settings-heading"
  use:enhance={saveOnChange}
>
  <h2 id="settings-heading">{m.settings_heading()}</h2>
  {#if shownOutcome === "failed"}
    <p class="form-error" role="alert">{m.settings_error_save()}</p>
  {:else if shownOutcome === "saved"}
    <p class="form-status" role="status">{m.settings_saved()}</p>
  {/if}

  <fieldset>
    <legend>{m.settings_theme_label()}</legend>
    <div class="option-grid">
      {#each themes as theme (theme.value)}
        <label class:active={selectedTheme === theme.value}>
          <input
            checked={selectedTheme === theme.value}
            name="theme"
            onchange={(event) =>
              choose({ theme: theme.value }, event.currentTarget)}
            type="radio"
            value={theme.value}
          />
          <span>{theme.label()}</span>
        </label>
      {/each}
    </div>
  </fieldset>

  <fieldset>
    <legend>{m.settings_locale_label()}</legend>
    <div class="option-grid">
      {#each localeOptions as locale (locale.value)}
        <label class:active={selectedLocale === locale.value}>
          <input
            checked={selectedLocale === locale.value}
            name="locale"
            onchange={(event) =>
              choose({ locale: locale.value }, event.currentTarget)}
            type="radio"
            value={locale.value}
          />
          <span>{locale.label()}</span>
        </label>
      {/each}
    </div>
  </fieldset>

  <noscript>
    <div class="actions">
      <button type="submit">{m.settings_save()}</button>
    </div>
  </noscript>
</form>

<style>
  .settings-panel {
    display: grid;
    max-width: 42rem;
    gap: 0.9rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  h2,
  p,
  fieldset {
    margin: 0;
    overflow-wrap: anywhere;
  }

  h2,
  legend {
    font-size: 1rem;
    font-weight: 700;
  }

  fieldset {
    display: grid;
    min-width: 0;
    gap: 0.65rem;
    border: 0;
    padding: 0;
  }

  legend {
    padding: 0;
  }

  .form-error,
  .form-status {
    border-radius: 6px;
    padding: 0.65rem;
  }

  .form-error {
    border: 1px solid
      color-mix(in oklab, var(--danger, #b42318) 65%, var(--border));
    background: color-mix(in oklab, var(--danger, #b42318) 12%, var(--surface));
    color: var(--danger, #b42318);
  }

  .form-status {
    border: 1px solid var(--border-strong);
    background: var(--accent-soft);
    color: var(--muted);
  }

  .option-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.6rem;
  }

  label {
    display: flex;
    min-height: 2.75rem;
    min-width: 0;
    align-items: center;
    gap: 0.5rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.55rem;
  }

  label.active {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  input {
    flex: 0 0 auto;
    width: 1rem;
    height: 1rem;
    accent-color: var(--accent);
  }

  span {
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    justify-content: flex-start;
  }

  button {
    min-height: 2.75rem;
    border: 1px solid var(--accent-strong);
    border-radius: 6px;
    background: var(--accent);
    color: var(--on-accent);
    padding: 0.65rem 0.9rem;
  }

  @media (max-width: 480px) {
    .option-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
