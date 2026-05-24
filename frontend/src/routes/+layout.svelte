<script lang="ts">
  import { page } from '$app/state';
  import AppShell from '$lib/components/AppShell.svelte';
  import '../app.css';

  let { data, children } = $props();
</script>

<AppShell activePath={page.url.pathname} locale={data.locale} tenant={data.tenant} theme={data.theme}>
  {@render children()}
</AppShell>