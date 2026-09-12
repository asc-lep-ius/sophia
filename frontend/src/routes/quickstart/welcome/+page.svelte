<script lang="ts">
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages.js";
</script>

<section class="step" aria-labelledby="quickstart-welcome-heading">
  <h2 id="quickstart-welcome-heading">{m.quickstart_welcome_heading()}</h2>
  <p>{m.quickstart_welcome_body()}</p>
  <ol class="cycle">
    <li>{m.quickstart_welcome_predict()}</li>
    <li>{m.quickstart_welcome_act()}</li>
    <li>{m.quickstart_welcome_reflect()}</li>
  </ol>
  <a class="primary" href={resolve("/quickstart/topics", {})}>
    {m.quickstart_continue()}
  </a>
</section>

<style>
  .step {
    display: grid;
    max-width: 48rem;
    min-width: 0;
    justify-items: start;
    gap: 0.75rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
    overflow-wrap: anywhere;
  }

  p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .cycle {
    display: grid;
    gap: 0.35rem;
    margin: 0;
    padding-left: 1.2rem;
  }

  li {
    overflow-wrap: anywhere;
  }

  a {
    display: inline-flex;
    min-height: 2.75rem;
    min-width: 3rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--accent-strong);
    border-radius: 6px;
    background: var(--accent);
    color: var(--on-accent);
    padding: 0.55rem 0.9rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }
</style>
