<script lang="ts">
  import { resolve } from '$app/paths';
  import { m } from '$lib/paraglide/messages.js';
  import type { Snippet } from 'svelte';

  import type { Locale } from '$lib/i18n/locale';
  import type { Theme } from '$lib/theme';

  type Tenant = {
    org_id: string;
    course_id: string;
    role: string;
  };

  type RouteId = '/' | '/dashboard' | '/login' | '/settings' | '/study';

  type Props = {
    activePath: string;
    children?: Snippet;
    locale: Locale;
    tenant: Tenant;
    theme: Theme;
  };

  let { activePath, children, locale, tenant, theme }: Props = $props();

  const navItems = [
    { path: '/', label: m.nav_home },
    { path: '/study', label: m.nav_study },
    { path: '/dashboard', label: m.nav_dashboard },
    { path: '/settings', label: m.nav_settings },
    { path: '/login', label: m.nav_login }
  ] satisfies { path: RouteId; label: () => string }[];
</script>

<svelte:head>
  <title>{m.app_title()} - {m.app_subtitle()}</title>
</svelte:head>

<a class="skip-link" href="#main-content">{m.skip_to_content()}</a>
<div class="shell" data-theme-label={theme} data-locale={locale}>
  <aside class="sidebar" aria-label={m.app_title()}>
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">S</span>
      <div class="brand-copy">
        <strong>{m.app_title()}</strong>
        <span>{m.app_subtitle()}</span>
      </div>
    </div>

    <nav class="nav-list" aria-label={m.app_subtitle()}>
      {#each navItems as item (item.path)}
        <a
          href={resolve(item.path, {})}
          aria-current={activePath === resolve(item.path, {}) ? 'page' : undefined}
          >{item.label()}</a
        >
      {/each}
    </nav>

    <dl class="tenant-panel" aria-label="Tenant">
      <div>
        <dt>{m.tenant_org()}</dt>
        <dd>{tenant.org_id}</dd>
      </div>
      <div>
        <dt>{m.tenant_course()}</dt>
        <dd>{tenant.course_id}</dd>
      </div>
      <div>
        <dt>{m.tenant_role()}</dt>
        <dd>{tenant.role}</dd>
      </div>
    </dl>
  </aside>

  <div class="workarea">
    <main id="main-content" tabindex="-1">
      {#if children}
        {@render children()}
      {/if}
    </main>
    <footer>{m.footer_status()}</footer>
  </div>
</div>

<style>
  .skip-link {
    position: fixed;
    z-index: 20;
    top: 0.75rem;
    left: 0.75rem;
    transform: translateY(-150%);
    border-radius: 6px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
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
    flex-direction: column;
    gap: 1.25rem;
    min-width: 0;
    border-right: 1px solid var(--border);
    background: var(--surface);
    padding: 1rem;
  }

  .brand {
    display: flex;
    align-items: center;
    min-width: 0;
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

  .brand-copy {
    display: grid;
    min-width: 0;
    gap: 0.1rem;
  }

  .brand-copy strong,
  .brand-copy span,
  .tenant-panel dd,
  .tenant-panel dt,
  footer {
    overflow-wrap: anywhere;
  }

  .brand-copy span,
  .tenant-panel dt,
  footer {
    color: var(--muted);
    font-size: 0.875rem;
  }

  .nav-list {
    display: grid;
    gap: 0.35rem;
  }

  .nav-list a {
    min-height: 2.75rem;
    border-radius: 6px;
    padding: 0.7rem 0.8rem;
    text-decoration: none;
  }

  .nav-list a[aria-current='page'],
  .nav-list a:hover {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  .tenant-panel {
    display: grid;
    gap: 0.7rem;
    margin: auto 0 0;
    border-top: 1px solid var(--border);
    padding-top: 1rem;
  }

  .tenant-panel div {
    display: grid;
    gap: 0.15rem;
  }

  .tenant-panel dt,
  .tenant-panel dd {
    margin: 0;
  }

  .workarea {
    display: grid;
    min-width: 0;
    grid-template-rows: minmax(0, 1fr) auto;
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

  @media (max-width: 720px) {
    .shell {
      display: block;
    }

    .sidebar {
      border-right: 0;
      border-bottom: 1px solid var(--border);
    }

    .nav-list {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    main {
      padding: 1rem;
    }
  }
</style>