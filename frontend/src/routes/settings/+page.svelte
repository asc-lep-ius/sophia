<script lang="ts">
  import { page } from "$app/state";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { m } from "$lib/paraglide/messages.js";
  import { normalizeTheme, persistTheme, type Theme } from "$lib/theme";

  type SettingsState = {
    locale: string;
    selected_learning_path_id?: string | null;
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
  ] satisfies { label: () => string; value: string }[];

  const settings = $derived(
    form?.settings ?? data.settings ?? fallbackSettings(data),
  );
  const persistedTheme = $derived(normalizeTheme(settings.theme));
  const selectedLocale = $derived(settings.locale);
  const selectedLearningPathId = $derived(settings.selected_learning_path_id ?? "");

  let selectedTheme = $derived<Theme>(persistedTheme);

  function selectTheme(theme: Theme) {
    selectedTheme = theme;
    persistTheme(theme);
  }

  function fallbackSettings(pageData: SettingsPageData): SettingsState {
    return {
      locale: pageData.locale,
      selected_learning_path_id: null,
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

<form class="settings-panel" method="POST" aria-labelledby="settings-heading">
  <h2 id="settings-heading">{m.settings_heading()}</h2>
  {#if form?.error}
    <p class="form-error" role="alert">{m.settings_error_save()}</p>
  {:else if form?.settings}
    <p class="form-status" role="status">{m.settings_saved()}</p>
  {/if}

  <input name="selected_learning_path_id" type="hidden" value={selectedLearningPathId} />

  <fieldset>
    <legend>{m.settings_theme_label()}</legend>
    <div class="option-grid">
      {#each themes as theme (theme.value)}
        <label class:active={selectedTheme === theme.value}>
          <input
            checked={selectedTheme === theme.value}
            name="theme"
            onchange={() => selectTheme(theme.value)}
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
            type="radio"
            value={locale.value}
          />
          <span>{locale.label()}</span>
        </label>
      {/each}
    </div>
  </fieldset>

  <div class="actions">
    <button type="submit">{m.settings_save()}</button>
  </div>
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
    color: #ffffff;
    padding: 0.65rem 0.9rem;
  }

  @media (max-width: 480px) {
    .option-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
