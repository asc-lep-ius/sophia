<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { m } from '$lib/paraglide/messages.js';
</script>

<PageHeader heading={m.login_heading()} summary={m.login_summary()} />

<form class="login-form" aria-labelledby="login-form-heading">
  <h2 id="login-form-heading">{m.login_heading()}</h2>
  <label>
    <span>{m.login_email_label()}</span>
    <input autocomplete="username" inputmode="email" name="username" type="email" />
  </label>
  <label>
    <span>{m.login_password_label()}</span>
    <input autocomplete="current-password" name="password" type="password" />
  </label>
  <button type="button">{m.login_submit()}</button>
</form>

<style>
  .login-form {
    display: grid;
    max-width: 30rem;
    gap: 0.85rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
  }

  h2 {
    margin: 0;
    font-size: 1rem;
  }

  label {
    display: grid;
    gap: 0.35rem;
    font-weight: 700;
  }

  input {
    min-height: 2.75rem;
    min-width: 0;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.65rem;
  }

  button {
    min-height: 2.75rem;
    border: 1px solid var(--accent-strong);
    border-radius: 6px;
    background: var(--accent);
    color: #ffffff;
    padding: 0.65rem;
  }
</style>