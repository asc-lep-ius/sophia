<script lang="ts">
  import { page } from '$app/state';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { m } from '$lib/paraglide/messages.js';
  import { normalizeTheme, persistTheme, type Theme } from '$lib/theme';

  const themes = [
    { label: m.settings_theme_light, value: 'light' },
    { label: m.settings_theme_dark, value: 'dark' },
    { label: m.settings_theme_oled, value: 'oled' }
  ] satisfies { label: () => string; value: Theme }[];

  let selectedTheme = $state<Theme>(normalizeTheme(page.data.theme));

  function selectTheme(theme: Theme) {
    selectedTheme = theme;
    persistTheme(theme);
  }
</script>

<PageHeader heading={m.settings_heading()} summary={m.settings_summary()} />

<section class="settings-panel" aria-labelledby="settings-theme-heading">
  <h2 id="settings-theme-heading">{m.settings_theme_label()}</h2>
  <div class="theme-options" role="group" aria-label={m.settings_theme_label()}>
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

  <h2>{m.settings_locale_label()}</h2>
  <p>{m.settings_locale_caption()}</p>
</section>

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
  p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  h2 {
    font-size: 1rem;
  }

  p {
    color: var(--muted);
    line-height: 1.55;
  }

  .theme-options {
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

  @media (max-width: 480px) {
    .theme-options {
      grid-template-columns: 1fr;
    }
  }
</style>