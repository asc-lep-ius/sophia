<script lang="ts">
  import { DRAWER_PARAM } from "$lib/content/filters";
  import { LANGUAGE_PARAM } from "$lib/content/language";
  import { m } from "$lib/paraglide/messages.js";
  import type { Snippet } from "svelte";

  type Props = {
    /** Already-resolved path of the list this filters — the form's target. */
    action: string;
    /** Rendered inside the form; every control must carry a `name`. */
    fields: Snippet;
    /**
     * The content language, which is the one piece of state this form carries
     * without a control of its own.
     *
     * Deliberately this and nothing else. An earlier version took the whole
     * filter set as hidden inputs, which put a second field of the same name
     * beside every visible control: forms serialise in tree order and
     * `searchParams.get` reads the first value, so changing a filter submitted
     * the old value ahead of the new one and silently did nothing.
     */
    lang?: string | null;
    open: boolean;
  };

  let { action, fields, lang = null, open }: Props = $props();
</script>

<!--
  Below 720 px the panel is a drawer: hidden until the trigger opens it, so a
  filter set never pushes the list it filters off the first screen. Above that
  width the same markup is an inline filter bar and the trigger is gone.

  Opening it is a submit rather than a script: the "Filters" button carries
  `filters=open` as its own name and value, so the browser reloads the list
  with the drawer showing and the current filters intact. That makes the
  drawer's state a URL fact — reload-safe, shareable, closed by the back
  button — and, more importantly, makes it reachable before hydration.

  The fields stay in the DOM while the drawer is closed. `display: none` does
  not exclude a control from a submission, so whichever button is pressed
  carries the filters that are already in effect.
-->
<section class="filters" aria-labelledby="filter-heading">
  <!--
    An empty sibling form is what "clear filters" submits. A button inside one
    form may target another through `form=`, and submitting a form with no
    fields lands on the bare list path — so the reset is a real navigation
    rather than a hand-built href, and needs no script either.
  -->
  <form id="filter-reset" method="get" {action}></form>

  <form class="filter-form" method="get" {action}>
    {#if lang}
      <input type="hidden" name={LANGUAGE_PARAM} value={lang} />
    {/if}

    <div class="filter-bar">
      <h2 id="filter-heading">{m.content_filters_heading()}</h2>
      {#if open}
        <button class="drawer-toggle" type="submit"
          >{m.content_filters_close()}</button
        >
      {:else}
        <button
          class="drawer-toggle"
          type="submit"
          name={DRAWER_PARAM}
          value="open">{m.content_filters_open()}</button
        >
      {/if}
    </div>

    <div class="filter-panel" class:open>
      {@render fields()}
      <div class="filter-actions">
        <button type="submit">{m.content_filters_apply()}</button>
        <button class="reset" type="submit" form="filter-reset"
          >{m.content_filters_reset()}</button
        >
      </div>
    </div>
  </form>
</section>

<style>
  .filters {
    min-width: 0;
    margin-bottom: 1rem;
  }

  .filter-form {
    display: grid;
    min-width: 0;
    gap: 0.75rem;
  }

  .filter-bar {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  h2 {
    margin: 0;
    font-size: 1rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .drawer-toggle {
    display: none;
  }

  .filter-panel {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    align-items: end;
    gap: 0.75rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 0.9rem;
  }

  .filter-actions {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.75rem;
  }

  button {
    display: inline-flex;
    min-height: 2.75rem;
    min-width: 2.75rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.8rem;
    font: inherit;
    overflow-wrap: anywhere;
    cursor: pointer;
  }

  button.reset {
    border-color: transparent;
    background: none;
    color: var(--accent-strong);
    text-decoration: underline;
  }

  @media (max-width: 720px) {
    .drawer-toggle {
      display: inline-flex;
    }

    .filter-panel {
      display: none;
      grid-template-columns: minmax(0, 1fr);
    }

    .filter-panel.open {
      display: grid;
    }

    .filter-actions {
      flex-wrap: wrap;
    }
  }
</style>
