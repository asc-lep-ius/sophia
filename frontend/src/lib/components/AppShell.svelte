<script lang="ts">
  import { resolve } from "$app/paths";
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages.js";
  import type { Snippet } from "svelte";

  import type { Locale } from "$lib/i18n/locale";
  import type { Theme } from "$lib/theme";

  type Tenant = {
    org_id: string;
    learning_path_id: string;
    role: string;
  };

  type ShellUser = {
    displayName?: string | null;
    email?: string | null;
    id: string;
    name?: string | null;
  };

  type RouteId = "/" | "/dashboard" | "/login" | "/settings" | "/study";

  type Props = {
    activePath: string;
    authenticated?: boolean;
    children?: Snippet;
    locale: Locale;
    tenant: Tenant;
    theme: Theme;
    user?: ShellUser | null;
  };

  let {
    activePath,
    authenticated = false,
    children,
    locale,
    tenant,
    theme,
    user = null,
  }: Props = $props();

  const navItems = [
    { path: "/", label: m.nav_home },
    { path: "/study", label: m.nav_study },
    { path: "/dashboard", label: m.nav_dashboard },
    { path: "/settings", label: m.nav_settings },
    { path: "/login", label: m.nav_login },
  ] satisfies { path: RouteId; label: () => string }[];
  const focusableDialogSelector =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  let drawerOpen = $state(false);
  let commandPaletteOpen = $state(false);
  let commandSearch = $state("");
  let drawerDialog = $state<HTMLDialogElement | null>(null);
  let drawerTrigger = $state<HTMLButtonElement | null>(null);
  let drawerCloseButton = $state<HTMLButtonElement | null>(null);
  let commandDialog = $state<HTMLDialogElement | null>(null);
  let commandTrigger = $state<HTMLButtonElement | null>(null);
  let commandInput = $state<HTMLInputElement | null>(null);
  let previousCommandFocus = $state<HTMLElement | null>(null);

  const sessionName = $derived(
    user?.displayName ?? user?.name ?? user?.email ?? m.session_user_fallback(),
  );
  const sessionState = $derived(
    authenticated ? m.session_signed_in() : m.session_guest(),
  );
  const filteredCommands = $derived.by(() => {
    const query = commandSearch.trim().toLocaleLowerCase(locale);
    if (!query) {
      return navItems;
    }
    return navItems.filter((item) =>
      item.label().toLocaleLowerCase(locale).includes(query),
    );
  });

  async function openDrawer() {
    drawerOpen = true;
    await tick();
    openModalDialog(drawerDialog);
    drawerCloseButton?.focus();
  }

  async function closeDrawer(restoreFocus = true) {
    drawerOpen = false;
    closeModalDialog(drawerDialog);
    await tick();
    if (restoreFocus) {
      drawerTrigger?.focus();
    }
  }

  async function openCommandPalette() {
    previousCommandFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    commandSearch = "";
    commandPaletteOpen = true;
    await tick();
    openModalDialog(commandDialog);
    commandInput?.focus();
  }

  async function closeCommandPalette(restoreFocus = true) {
    commandPaletteOpen = false;
    commandSearch = "";
    closeModalDialog(commandDialog);
    await tick();
    if (restoreFocus) {
      (previousCommandFocus ?? commandTrigger)?.focus();
    }
  }

  function openModalDialog(dialog: HTMLDialogElement | null) {
    if (!dialog || dialog.open) {
      return;
    }

    if (typeof dialog.showModal === "function") {
      dialog.showModal();
      return;
    }

    dialog.setAttribute("open", "");
  }

  function closeModalDialog(dialog: HTMLDialogElement | null) {
    if (!dialog?.open) {
      return;
    }

    if (typeof dialog.close === "function") {
      dialog.close();
      return;
    }

    dialog.removeAttribute("open");
  }

  function handleDrawerCancel(event: Event) {
    event.preventDefault();
    void closeDrawer();
  }

  function handleCommandPaletteCancel(event: Event) {
    event.preventDefault();
    void closeCommandPalette();
  }

  function handleModalTabKeydown(
    event: KeyboardEvent,
    dialog: HTMLDialogElement | null,
  ) {
    if (event.key !== "Tab" || !dialog) {
      return;
    }

    const focusableElements = Array.from(
      dialog.querySelectorAll<HTMLElement>(focusableDialogSelector),
    ).filter((element) => element.tabIndex >= 0);
    const firstElement = focusableElements.at(0);
    const lastElement = focusableElements.at(-1);

    if (!firstElement || !lastElement) {
      event.preventDefault();
      dialog.focus();
      return;
    }

    const activeElement = document.activeElement;
    if (
      event.shiftKey &&
      (activeElement === firstElement || !dialog.contains(activeElement))
    ) {
      event.preventDefault();
      lastElement.focus();
      return;
    }

    if (
      !event.shiftKey &&
      (activeElement === lastElement || !dialog.contains(activeElement))
    ) {
      event.preventDefault();
      firstElement.focus();
    }
  }

  function handleGlobalKeydown(event: KeyboardEvent) {
    const key = event.key.toLocaleLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "k") {
      event.preventDefault();
      if (commandPaletteOpen) {
        void closeCommandPalette();
      } else {
        void openCommandPalette();
      }
      return;
    }

    if (event.key === "Escape") {
      if (commandPaletteOpen) {
        event.preventDefault();
        void closeCommandPalette();
        return;
      }
      if (drawerOpen) {
        event.preventDefault();
        void closeDrawer();
      }
    }
  }

  function handleCommandSearchKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter" || filteredCommands.length === 0) {
      return;
    }

    event.preventDefault();
    const firstCommand = filteredCommands[0];
    if (firstCommand) {
      window.location.assign(routeHref(firstCommand.path));
    }
  }

  function routeHref(path: RouteId): string {
    return resolve(path, {});
  }

  function routeIsActive(path: RouteId): boolean {
    const target = normalizeRoute(routeHref(path));
    const active = normalizeRoute(activePath);
    if (target === normalizeRoute(routeHref("/"))) {
      return active === target;
    }
    return active === target || active.startsWith(`${target}/`);
  }

  function normalizeRoute(path: string): string {
    const pathname = path.split(/[?#]/, 1)[0] ?? path;
    const trimmed = pathname.replace(/\/+$/, "");
    return trimmed || normalizeBaseRoute();
  }

  function normalizeBaseRoute(): string {
    return resolve("/", {}).replace(/\/+$/, "") || "/app";
  }
</script>

<svelte:head>
  <title>{m.app_title()} - {m.app_subtitle()}</title>
</svelte:head>

<svelte:window onkeydown={handleGlobalKeydown} />

<a class="skip-link" href="#main-content">{m.skip_to_content()}</a>
<div class="shell" data-theme-label={theme} data-locale={locale}>
  <aside class="sidebar" aria-label={m.app_title()}>
    <div class="brand">
      <span class="brand-mark" aria-hidden="true"
        >{m.app_title().slice(0, 1)}</span
      >
      <div class="brand-copy">
        <strong>{m.app_title()}</strong>
        <span>{m.app_subtitle()}</span>
      </div>
    </div>

    <nav class="nav-list" aria-label={m.nav_primary_label()}>
      {#each navItems as item (item.path)}
        <a
          href={resolve(item.path, {})}
          aria-current={routeIsActive(item.path) ? "page" : undefined}
          >{item.label()}</a
        >
      {/each}
    </nav>

    <dl class="tenant-panel" aria-label={m.tenant_label()}>
      <div>
        <dt>{m.tenant_org()}</dt>
        <dd>{tenant.org_id}</dd>
      </div>
      <div>
        <dt>{m.tenant_course()}</dt>
        <dd>{tenant.learning_path_id}</dd>
      </div>
      <div>
        <dt>{m.tenant_role()}</dt>
        <dd>{tenant.role}</dd>
      </div>
    </dl>
  </aside>

  <div class="workarea">
    <header class="topbar" aria-label={m.session_label()}>
      <button
        bind:this={drawerTrigger}
        class="icon-text-button mobile-menu-button"
        type="button"
        aria-controls={drawerOpen ? "mobile-navigation-drawer" : undefined}
        aria-expanded={drawerOpen}
        onclick={openDrawer}
      >
        {m.nav_mobile_open()}
      </button>

      <div class="session-summary" aria-label={m.session_label()}>
        <span>{sessionState}</span>
        <strong>{sessionName}</strong>
      </div>

      <dl class="shell-metadata" aria-label={m.tenant_label()}>
        <div>
          <dt>{m.tenant_course()}</dt>
          <dd>{tenant.learning_path_id}</dd>
        </div>
        <div>
          <dt>{m.theme_label()}</dt>
          <dd>{theme}</dd>
        </div>
      </dl>

      <button
        bind:this={commandTrigger}
        class="icon-text-button command-trigger"
        type="button"
        aria-controls={commandPaletteOpen ? "command-palette" : undefined}
        aria-expanded={commandPaletteOpen}
        aria-keyshortcuts="Control+K Meta+K"
        onclick={openCommandPalette}
      >
        <span>{m.command_palette_open()}</span>
        <kbd>{m.command_palette_shortcut()}</kbd>
      </button>
    </header>

    <main id="main-content" tabindex="-1">
      {#if children}
        {@render children()}
      {/if}
    </main>
    <footer>{m.footer_status()}</footer>
  </div>
</div>

{#if drawerOpen}
  <dialog
    bind:this={drawerDialog}
    id="mobile-navigation-drawer"
    class="drawer"
    aria-labelledby="drawer-title"
    oncancel={handleDrawerCancel}
    onkeydown={(event) => handleModalTabKeydown(event, drawerDialog)}
  >
    <div class="drawer-header">
      <h2 id="drawer-title">{m.nav_mobile_title()}</h2>
      <button
        bind:this={drawerCloseButton}
        type="button"
        onclick={() => closeDrawer()}
      >
        {m.nav_mobile_close()}
      </button>
    </div>
    <nav class="drawer-nav" aria-label={m.nav_primary_label()}>
      {#each navItems as item (item.path)}
        <a
          href={resolve(item.path, {})}
          aria-current={routeIsActive(item.path) ? "page" : undefined}
          onclick={() => closeDrawer(false)}>{item.label()}</a
        >
      {/each}
    </nav>
    <dl class="drawer-tenant" aria-label={m.tenant_label()}>
      <div>
        <dt>{m.session_label()}</dt>
        <dd>{sessionName}</dd>
      </div>
      <div>
        <dt>{m.tenant_org()}</dt>
        <dd>{tenant.org_id}</dd>
      </div>
      <div>
        <dt>{m.tenant_course()}</dt>
        <dd>{tenant.learning_path_id}</dd>
      </div>
    </dl>
  </dialog>
{/if}

{#if commandPaletteOpen}
  <dialog
    bind:this={commandDialog}
    id="command-palette"
    class="command-palette"
    aria-labelledby="command-title"
    oncancel={handleCommandPaletteCancel}
    onkeydown={(event) => handleModalTabKeydown(event, commandDialog)}
  >
    <div class="command-header">
      <h2 id="command-title">{m.command_palette_title()}</h2>
      <button type="button" onclick={() => closeCommandPalette()}
        >{m.command_palette_close()}</button
      >
    </div>

    <label class="sr-only" for="command-search"
      >{m.command_palette_search()}</label
    >
    <input
      bind:this={commandInput}
      bind:value={commandSearch}
      id="command-search"
      type="search"
      autocomplete="off"
      onkeydown={handleCommandSearchKeydown}
      placeholder={m.command_palette_search()}
    />

    <nav
      id="command-list"
      class="command-list"
      aria-label={m.command_palette_title()}
    >
      {#each filteredCommands as item (item.path)}
        <a
          href={resolve(item.path, {})}
          aria-current={routeIsActive(item.path) ? "page" : undefined}
          onclick={() => closeCommandPalette(false)}>{item.label()}</a
        >
      {:else}
        <p>{m.command_palette_empty()}</p>
      {/each}
    </nav>
  </dialog>
{/if}

<style>
  .skip-link {
    position: fixed;
    z-index: 30;
    top: 0.75rem;
    left: 0.75rem;
    transform: translateY(-150%);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface);
    padding: 0.65rem 0.9rem;
  }

  .skip-link:focus {
    transform: translateY(0);
  }

  .shell {
    display: grid;
    grid-template-columns: minmax(13.5rem, 16rem) minmax(0, 1fr);
    min-height: 100vh;
    background: var(--background);
  }

  .sidebar {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 1.25rem;
    border-right: 1px solid var(--border);
    background: var(--surface);
    padding: 1rem;
  }

  .brand,
  .topbar,
  .drawer-header,
  .command-header {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.75rem;
  }

  .brand-mark {
    display: grid;
    flex: 0 0 2.5rem;
    width: 2.5rem;
    height: 2.5rem;
    place-items: center;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 800;
  }

  .brand-copy,
  .session-summary,
  .shell-metadata div,
  .tenant-panel div,
  .drawer-tenant div {
    display: grid;
    min-width: 0;
    gap: 0.1rem;
  }

  .brand-copy strong,
  .brand-copy span,
  .session-summary strong,
  .session-summary span,
  .shell-metadata dd,
  .shell-metadata dt,
  .tenant-panel dd,
  .tenant-panel dt,
  .drawer-tenant dd,
  .drawer-tenant dt,
  footer,
  h2,
  p,
  a,
  button,
  kbd {
    overflow-wrap: anywhere;
  }

  .brand-copy span,
  .session-summary span,
  .shell-metadata dt,
  .tenant-panel dt,
  .drawer-tenant dt,
  footer {
    color: var(--muted);
    font-size: 0.875rem;
  }

  .nav-list,
  .drawer-nav,
  .command-list {
    display: grid;
    gap: 0.35rem;
  }

  .nav-list a,
  .drawer-nav a,
  .command-list a {
    display: flex;
    min-height: 2.75rem;
    min-width: 0;
    align-items: center;
    border-radius: 6px;
    padding: 0.7rem 0.8rem;
    text-decoration: none;
  }

  .nav-list a[aria-current="page"],
  .nav-list a:hover,
  .drawer-nav a[aria-current="page"],
  .drawer-nav a:hover,
  .command-list a[aria-current="page"],
  .command-list a:hover {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  .tenant-panel,
  .drawer-tenant {
    display: grid;
    gap: 0.7rem;
    margin: auto 0 0;
    border-top: 1px solid var(--border);
    padding-top: 1rem;
  }

  .shell-metadata,
  .tenant-panel dt,
  .tenant-panel dd,
  .drawer-tenant dt,
  .drawer-tenant dd {
    margin: 0;
  }

  .workarea {
    display: grid;
    min-width: 0;
    grid-template-rows: auto minmax(0, 1fr) auto;
  }

  .topbar {
    min-height: 4rem;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    padding: 0.65rem 1.25rem;
  }

  .session-summary {
    flex: 1 1 auto;
  }

  .shell-metadata {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 10rem));
    gap: 0.7rem;
  }

  .icon-text-button,
  .drawer-header button,
  .command-header button {
    display: inline-flex;
    min-height: 2.75rem;
    min-width: 2.75rem;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.7rem;
  }

  .mobile-menu-button {
    display: none;
  }

  .command-trigger kbd {
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--muted);
    padding: 0.1rem 0.3rem;
    font-size: 0.75rem;
    line-height: 1.2;
  }

  main {
    width: min(100%, 72rem);
    min-width: 0;
    padding: 1.25rem;
  }

  footer {
    border-top: 1px solid var(--border);
    padding: 0.8rem 1.25rem;
  }

  .drawer,
  .command-palette {
    position: fixed;
    z-index: 25;
    display: grid;
    margin: 0;
    min-width: 0;
    border: 1px solid var(--border-strong);
    background: var(--surface);
    box-shadow: 0 1rem 2.5rem rgb(15 23 42 / 18%);
  }

  .drawer::backdrop,
  .command-palette::backdrop {
    background: rgb(15 23 42 / 35%);
  }

  .drawer {
    top: 0.5rem;
    bottom: 0.5rem;
    left: 0.5rem;
    width: min(20rem, calc(100vw - 1rem));
    align-content: start;
    gap: 1rem;
    overflow-y: auto;
    border-radius: 8px;
    padding: 0.9rem;
  }

  .drawer-header,
  .command-header {
    justify-content: space-between;
  }

  h2 {
    margin: 0;
    font-size: 1rem;
    line-height: 1.25;
  }

  .command-palette {
    top: 1rem;
    left: 50%;
    width: min(32rem, calc(100vw - 1.5rem));
    max-height: calc(100vh - 2rem);
    transform: translateX(-50%);
    gap: 0.75rem;
    overflow-y: auto;
    border-radius: 8px;
    padding: 0.9rem;
  }

  .command-palette input {
    min-height: 2.75rem;
    min-width: 0;
    width: 100%;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.65rem 0.75rem;
  }

  .command-list p {
    margin: 0;
    color: var(--muted);
    padding: 0.7rem 0.8rem;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  @media (max-width: 880px) {
    .shell-metadata {
      display: none;
    }
  }

  @media (max-width: 720px) {
    .shell {
      grid-template-columns: minmax(0, 1fr);
    }

    .sidebar {
      display: none;
    }

    .mobile-menu-button {
      display: inline-flex;
    }

    .topbar {
      align-items: stretch;
      padding: 0.6rem;
    }

    .session-summary {
      justify-content: center;
    }

    .command-trigger {
      flex: 0 1 auto;
    }

    .command-trigger kbd {
      display: none;
    }

    main {
      padding: 1rem;
    }
  }

  @media (max-width: 380px) {
    .topbar {
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 0.45rem;
    }

    .icon-text-button {
      padding-inline: 0.5rem;
    }

    .session-summary strong,
    .session-summary span {
      font-size: 0.82rem;
      line-height: 1.2;
    }
  }
</style>
