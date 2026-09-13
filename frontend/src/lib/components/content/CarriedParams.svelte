<script lang="ts">
  type Props = {
    /** Query parameters this navigation has to keep, as hidden fields. */
    params: Record<string, string>;
    /** One parameter to drop, when a control supplies it itself. */
    omit?: string;
  };

  let { params, omit = "" }: Props = $props();

  const fields = $derived(
    Object.entries(params).filter(([name]) => name !== omit),
  );
</script>

<!--
  The filters and the chosen content language, carried through a GET form.

  Every internal navigation on these pages is a form rather than an href with a
  query string appended, so the browser is what assembles the URL. That keeps
  the filter state addressable without any code concatenating a query, and it
  keeps the whole surface working before hydration.
-->
{#each fields as [name, value] (name)}
  <input type="hidden" {name} {value} />
{/each}
