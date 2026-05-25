<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import AppShell from '$lib/components/AppShell.svelte';
  import { startReservedWebVitals } from '$lib/metrics/webVitals';
  import '../app.css';

  let { data, children } = $props();

  onMount(() => {
    startReservedWebVitals();
  });
</script>

<AppShell activePath={page.url.pathname} locale={data.locale} tenant={data.tenant} theme={data.theme}>
  {@render children()}
</AppShell>