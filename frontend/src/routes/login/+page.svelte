<script lang="ts">
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { m } from "$lib/paraglide/messages.js";

  type LoginError = "invalid" | "required" | "unavailable";
  type LoginForm = {
    error?: LoginError;
    username?: string;
  };

  let { form }: { form?: LoginForm } = $props();

  const errorMessage = $derived(loginErrorMessage(form?.error));

  function loginErrorMessage(
    error: LoginError | undefined,
  ): string | undefined {
    if (error === "invalid") {
      return m.login_error_invalid_credentials();
    }
    if (error === "required") {
      return m.login_error_required();
    }
    if (error === "unavailable") {
      return m.login_error_unavailable();
    }
    return undefined;
  }
</script>

<PageHeader heading={m.login_heading()} summary={m.login_summary()} />

<form
  class="login-form"
  method="POST"
  aria-labelledby="login-form-heading"
  aria-describedby={errorMessage ? "login-error" : undefined}
>
  <h2 id="login-form-heading">{m.login_heading()}</h2>
  {#if errorMessage}
    <p id="login-error" class="form-error" role="alert">{errorMessage}</p>
  {/if}
  <label>
    <span>{m.login_email_label()}</span>
    <input
      autocomplete="username"
      inputmode="email"
      name="username"
      required
      type="email"
      value={form?.username ?? ""}
    />
  </label>
  <label>
    <span>{m.login_password_label()}</span>
    <input
      autocomplete="current-password"
      name="password"
      required
      type="password"
    />
  </label>
  <button type="submit">{m.login_submit()}</button>
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

  .form-error {
    margin: 0;
    border: 1px solid
      color-mix(in oklab, var(--danger, #b42318) 65%, var(--border));
    border-radius: 6px;
    background: color-mix(in oklab, var(--danger, #b42318) 12%, var(--surface));
    color: var(--danger, #b42318);
    padding: 0.65rem;
    overflow-wrap: anywhere;
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
