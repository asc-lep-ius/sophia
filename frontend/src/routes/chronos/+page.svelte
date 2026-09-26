<script lang="ts">
  import { resolve } from "$app/paths";
  import DueDate from "$lib/components/chronos/DueDate.svelte";
  import NoLearningPathNotice from "$lib/components/NoLearningPathNotice.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import { formatHours, type Deadline } from "$lib/chronos/deadlines";
  import { m } from "$lib/paraglide/messages.js";
  import type { ActionData, PageData } from "./$types";

  type Props = { data: PageData; form: ActionData };

  let { data, form }: Props = $props();

  const historyPath = resolve("/chronos/history", {});

  const typeLabels: Record<string, () => string> = {
    assignment: m.chronos_type_assignment,
    checkmark: m.chronos_type_checkmark,
    exam: m.chronos_type_exam,
    exam_registration: m.chronos_type_exam_registration,
    quiz: m.chronos_type_quiz,
  };

  const workload = $derived(data.workload.data);

  function typeLabel(deadline: Deadline): string {
    return (typeLabels[deadline.deadline_type] ?? m.chronos_type_other)();
  }
</script>

<PageHeader heading={m.chronos_heading()} summary={m.chronos_summary()} />

{#if form && "syncFailed" in form}
  <p class="notice error" role="alert">{m.chronos_sync_failed()}</p>
{:else if form && "completeFailed" in form}
  <p class="notice error" role="alert">{m.chronos_complete_failed()}</p>
{:else if form && "syncedCount" in form}
  <p class="notice" role="status">
    {(form.syncedCount ?? 0) === 0
      ? m.chronos_sync_none()
      : m.chronos_synced({ count: form.syncedCount ?? 0 })}
  </p>
{:else if form && "completedId" in form}
  <p class="notice" role="status">{m.chronos_completed()}</p>
{/if}

{#if data.learningPathId === null}
  <NoLearningPathNotice />
{:else}
  <PanelSection
    id="chronos-workload"
    heading={m.chronos_workload_heading()}
    status={data.workload.status}
    isEmpty={workload === null}
  >
    {#snippet empty()}
      <p class="empty-body">{m.chronos_workload_empty()}</p>
    {/snippet}

    <dl class="workload">
      <div>
        <dt>{m.chronos_workload_estimated()}</dt>
        <dd>{formatHours(workload?.total_estimated_hours ?? 0)}</dd>
      </div>
      <div>
        <dt>{m.chronos_workload_tracked()}</dt>
        <dd>{formatHours(workload?.total_tracked_hours ?? 0)}</dd>
      </div>
      <div>
        <dt>{m.chronos_workload_remaining()}</dt>
        <dd>{formatHours(workload?.remaining_hours ?? 0)}</dd>
      </div>
    </dl>
  </PanelSection>

  <PanelSection
    id="chronos-deadlines"
    heading={m.chronos_list_heading()}
    status={data.deadlines.status}
    isEmpty={data.deadlines.data.length === 0}
    note={m.chronos_horizon({ days: data.horizonDays })}
  >
    {#snippet empty()}
      <div class="empty-state">
        <p class="empty-title">{m.chronos_empty_title()}</p>
        <p class="empty-body">{m.chronos_empty_body()}</p>
        <form method="post" action="?/sync">
          <button class="primary" type="submit">{m.chronos_sync()}</button>
        </form>
      </div>
    {/snippet}

    <ul class="deadlines">
      {#each data.deadlines.data as deadline (deadline.id)}
        <li class="deadline">
          <div class="deadline-head">
            <span class="type">{typeLabel(deadline)}</span>
            <h3>{deadline.name}</h3>
          </div>
          <p class="course">{deadline.learning_path_name}</p>
          <DueDate
            dueAt={deadline.due_at}
            locale={data.uiLocale}
            now={data.now}
          />
          <p class="facts">
            {#if deadline.grade_weight !== null}
              <span
                >{m.chronos_weight({
                  percent: Math.round(deadline.grade_weight * 100),
                })}</span
              >
            {/if}
            {#if deadline.submission_status}
              <span>{m.chronos_submission({ status: deadline.submission_status })}</span>
            {/if}
          </p>
          <form method="post" action="?/complete">
            <input type="hidden" name="deadline_id" value={deadline.id} />
            <button type="submit">{m.chronos_complete()}</button>
          </form>
        </li>
      {/each}
    </ul>

    <form class="sync" method="post" action="?/sync">
      <button type="submit">{m.chronos_sync()}</button>
    </form>
  </PanelSection>

  <p class="history-link">
    <a href={historyPath}>{m.chronos_history_link()}</a>
  </p>
{/if}

<style>
  .workload {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
    margin: 0;
  }

  .workload div {
    display: grid;
    min-width: 0;
    gap: 0.1rem;
  }

  dt {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  dd {
    margin: 0;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .deadlines {
    display: grid;
    min-width: 0;
    gap: 0.75rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .deadline {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.4rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-raised);
    padding: 0.8rem;
  }

  .deadline-head {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.5rem;
  }

  .type {
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-size: 0.78rem;
    overflow-wrap: anywhere;
  }

  h3 {
    margin: 0;
    font-size: 1rem;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  .course,
  .facts,
  .notice,
  .empty-body,
  .empty-title,
  .history-link {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .course,
  .facts,
  .notice,
  .empty-body {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .facts {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .notice {
    margin-bottom: 0.75rem;
    font-size: 1rem;
  }

  .notice.error {
    color: var(--danger);
  }

  .empty-state {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.4rem;
  }

  .empty-title {
    font-weight: 700;
  }

  .sync,
  .history-link {
    margin-top: 0.75rem;
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

  button.primary {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }
</style>
