<script lang="ts">
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import NoLearningPathNotice from "$lib/components/NoLearningPathNotice.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import ReviewCard from "$lib/components/review/ReviewCard.svelte";
  import { completeReview } from "$lib/api/review";
  import { m } from "$lib/paraglide/messages.js";
  import { ReviewQueueStore } from "$lib/review/queue.svelte";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const dueTopics = $derived(
    data.due.data.filter((review) => review.is_due).map((review) => review.topic),
  );

  // A string, not the array it came from: `dueTopics` is a `$derived` that
  // returns a fresh array every time it runs, so depending on it directly
  // would rebuild the queue on any invalidation at all.
  const queueKey = $derived(dueTopics.join("|"));

  // Rebuilt only when the queue itself changes, never when an unrelated
  // `invalidateAll` hands the page a fresh data object — that would throw away
  // a recall attempt the learner is part-way through writing.
  const store = $derived.by(() => {
    void queueKey;
    return untrack(
      () =>
        new ReviewQueueStore({
          pacing: {
            minPromptDwellMs: data.pacing.prompt_min_dwell_ms,
            minRecallChars: data.pacing.elaboration_min_chars,
          },
          submit: async (submission) => {
            await completeReview(
              {
                csrfToken: data.csrfToken ?? "",
                learningPathId: data.learningPathId ?? 0,
              },
              { selfRating: submission.selfRating, topic: submission.topic },
            );
          },
          topics: dueTopics,
        }),
    );
  });

  // `$effect` cleanup does not run on a tab close or hard reload, which is
  // exactly when a held review would be lost.
  $effect(() => {
    const current = store;
    const flush = () => current.flush();
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  });
</script>

<PageHeader heading={m.review_heading()} summary={m.review_summary()} />

{#if data.learningPathId === null}
  <NoLearningPathNotice />
{:else if data.due.status === "unauthorized"}
  <p class="notice" role="status">{m.dashboard_panel_unauthorized()}</p>
{:else if data.due.status === "error"}
  <p class="notice error" role="status">{m.dashboard_panel_error()}</p>
{:else if dueTopics.length === 0}
  <section class="empty" aria-labelledby="review-empty-heading">
    <h2 id="review-empty-heading">{m.review_empty_title()}</h2>
    <p>{m.review_empty_body()}</p>
    <div class="actions">
      <a class="primary" href={resolve("/study", {})}>{m.dashboard_open_study()}</a>
      <a href={resolve("/dashboard", {})}>{m.quickstart_done_dashboard()}</a>
    </div>
  </section>
{:else if store.finished}
  <section class="summary" aria-labelledby="review-summary-heading">
    <h2 id="review-summary-heading">{m.review_finished_title()}</h2>
    <p>{m.review_finished_body({ count: store.gradedCount })}</p>
    <a class="primary" href={resolve("/dashboard", {})}>{m.quickstart_done_dashboard()}</a>
  </section>
{:else}
  <ReviewCard {store} />
{/if}

<style>
  .empty,
  .summary {
    display: grid;
    max-width: 52rem;
    min-width: 0;
    justify-items: start;
    gap: 0.6rem;
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

  .notice {
    margin: 0;
    color: var(--muted);
    overflow-wrap: anywhere;
  }

  .notice.error {
    color: var(--danger);
  }

  .actions {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  a {
    display: inline-flex;
    min-height: 2.75rem;
    min-width: 3rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--surface-raised);
    color: var(--text);
    padding: 0.55rem 0.9rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }

  a.primary {
    border-color: var(--accent-strong);
    background: var(--accent);
    color: var(--on-accent);
  }
</style>
