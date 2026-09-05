<script lang="ts">
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages.js";

  type Props = {
    open: boolean;
    onClose: () => void;
  };

  let { open, onClose }: Props = $props();

  let dialog = $state<HTMLDialogElement | null>(null);
  let closeButton = $state<HTMLButtonElement | null>(null);

  const shortcuts = [
    { keys: "Space", describe: () => m.study_keyboard_reveal() },
    { keys: "1 – 4", describe: () => m.study_keyboard_grade() },
    { keys: "U", describe: () => m.study_keyboard_undo() },
    { keys: "P", describe: () => m.study_keyboard_pause() },
    { keys: "F", describe: () => m.study_keyboard_focus() },
    { keys: "?", describe: () => m.study_keyboard_help_key() },
  ];

  $effect(() => {
    if (!open) {
      return;
    }
    void (async () => {
      await tick();
      if (dialog && !dialog.open && typeof dialog.showModal === "function") {
        dialog.showModal();
      }
      closeButton?.focus();
    })();
  });

  function handleCancel(event: Event) {
    event.preventDefault();
    onClose();
  }
</script>

{#if open}
  <dialog
    bind:this={dialog}
    class="shortcuts"
    aria-labelledby="study-shortcuts-title"
    oncancel={handleCancel}
  >
    <div class="header">
      <h2 id="study-shortcuts-title">{m.study_keyboard_help()}</h2>
      <button bind:this={closeButton} type="button" onclick={onClose}>
        {m.study_keyboard_help_close()}
      </button>
    </div>
    <dl>
      {#each shortcuts as shortcut (shortcut.keys)}
        <div>
          <dt><kbd>{shortcut.keys}</kbd></dt>
          <dd>{shortcut.describe()}</dd>
        </div>
      {/each}
    </dl>
    <p class="note">{m.study_keyboard_note()}</p>
  </dialog>
{/if}

<style>
  .shortcuts {
    position: fixed;
    z-index: 25;
    top: 1rem;
    left: 50%;
    display: grid;
    width: min(26rem, calc(100vw - 1.5rem));
    max-height: calc(100vh - 2rem);
    transform: translateX(-50%);
    gap: 0.75rem;
    overflow-y: auto;
    margin: 0;
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    background: var(--surface);
    padding: 0.9rem;
  }

  .shortcuts::backdrop {
    background: rgb(15 23 42 / 35%);
  }

  .header {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  h2 {
    margin: 0;
    font-size: 1rem;
    overflow-wrap: anywhere;
  }

  button {
    min-height: 2.75rem;
    min-width: 2.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.5rem 0.7rem;
    overflow-wrap: anywhere;
  }

  dl {
    display: grid;
    gap: 0.5rem;
    margin: 0;
  }

  dl div {
    display: grid;
    min-width: 0;
    grid-template-columns: minmax(3.5rem, auto) minmax(0, 1fr);
    gap: 0.6rem;
  }

  dt,
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }

  kbd {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.05rem 0.35rem;
    font-size: 0.8rem;
  }

  .note {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }
</style>
