<script lang="ts">
  import CarriedParams from "./CarriedParams.svelte";

  type Props = {
    /** Already-resolved destination path. */
    action: string;
    label: string;
    params?: Record<string, string>;
    /** Draws the control as the page's primary call to action. */
    primary?: boolean;
  };

  let { action, label, params = {}, primary = false }: Props = $props();
</script>

<!--
  A navigation that has to carry state, expressed as the thing it actually is.

  An `<a>` would need a query string built by hand; a GET form lets the browser
  build it from the fields, which is what keeps `?lang=` alive across a hop
  between the content surfaces without a single concatenated URL.
-->
<form class="carried-link" method="get" {action}>
  <CarriedParams {params} />
  <button type="submit" class:primary>{label}</button>
</form>

<style>
  .carried-link {
    display: inline;
  }

  button {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    border: 1px solid transparent;
    border-radius: 6px;
    background: none;
    color: var(--accent-strong);
    padding: 0.4rem 0;
    font: inherit;
    text-decoration: underline;
    overflow-wrap: anywhere;
    cursor: pointer;
  }

  button.primary {
    border-color: var(--border-strong);
    background: var(--accent-soft);
    padding-inline: 0.9rem;
    text-decoration: none;
  }
</style>
