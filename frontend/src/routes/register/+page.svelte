<script lang="ts">
  import { resolve } from "$app/paths";
  import CarriedLink from "$lib/components/content/CarriedLink.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import {
    COURSE_PARAM,
    openGroups,
    registrationCountdown,
  } from "$lib/registration/tiss";
  import { m } from "$lib/paraglide/messages.js";
  import type { ActionData, PageData } from "./$types";

  type Props = { data: PageData; form: ActionData };

  let { data, form }: Props = $props();

  const registerPath = resolve("/register", {});
  const settingsPath = resolve("/settings", {});

  const errorMessages = {
    course_number: m.register_error_course_number,
    session: m.register_error_session,
    unavailable: m.register_error_unavailable,
  } as const;

  const detail = $derived(data.detail);
  const available = $derived(openGroups(detail?.groups ?? []));

  const countdown = $derived(
    registrationCountdown(
      detail?.target?.registration_start ?? null,
      new Date(data.now),
    ),
  );

  const countdownText = $derived.by(() => {
    if (countdown.state === "open") {
      return m.register_window_open();
    }
    if (countdown.state === "unknown") {
      return m.register_window_unknown();
    }
    return m.register_window_waiting({
      days: countdown.days,
      hours: countdown.hours,
      minutes: countdown.minutes,
    });
  });

  function registeredLabel(registered: boolean): string {
    return registered ? m.register_reg_yes() : m.register_reg_no();
  }
</script>

<PageHeader heading={m.register_heading()} summary={m.register_summary()} />

{#if form && "error" in form && form.error}
  <p class="notice error" role="alert">{errorMessages[form.error]()}</p>
{:else if form && "result" in form}
  <p class="notice" class:error={!form.result.success} role="status">
    {form.result.success
      ? m.register_result_success({ message: form.result.message })
      : m.register_result_failed({ message: form.result.message })}
  </p>
{/if}

{#if data.connection === "session_missing"}
  <section class="state" aria-labelledby="register-session-heading">
    <h2 id="register-session-heading">{m.register_session_missing_title()}</h2>
    <p>{m.register_session_missing_body()}</p>
    <a class="primary" href={settingsPath}>{m.register_open_settings()}</a>
  </section>
{:else if data.connection === "session_expired"}
  <section class="state" aria-labelledby="register-expired-heading">
    <h2 id="register-expired-heading">{m.register_session_expired_title()}</h2>
    <p>{m.register_session_expired_body()}</p>
    <a class="primary" href={settingsPath}>{m.register_open_settings()}</a>
  </section>
{:else}
  <PanelSection
    id="register-favorites"
    heading={m.register_favorites_heading()}
    status={data.favorites.status}
    isEmpty={data.favorites.data.length === 0}
  >
    {#snippet empty()}
      <div class="empty-state">
        <p class="empty-title">{m.register_favorites_empty_title()}</p>
        <p class="empty-body">{m.register_favorites_empty_body()}</p>
      </div>
    {/snippet}

    <ul class="favorites">
      {#each data.favorites.data as favorite (favorite.course_number)}
        <li class="favorite" class:selected={favorite.course_number === data.selectedCourse}>
          <div class="favorite-head">
            <h3>{favorite.title}</h3>
            <span class="number">{favorite.course_number}</span>
          </div>
          <ul class="flags">
            <li>{m.register_reg_lva()}: {registeredLabel(favorite.lva_registered)}</li>
            <li>{m.register_reg_group()}: {registeredLabel(favorite.group_registered)}</li>
            <li>{m.register_reg_exam()}: {registeredLabel(favorite.exam_registered)}</li>
          </ul>
          {#if favorite.course_number === data.selectedCourse}
            <CarriedLink action={registerPath} label={m.register_close_course()} />
          {:else}
            <CarriedLink
              action={registerPath}
              label={m.register_open_course()}
              params={{ [COURSE_PARAM]: favorite.course_number }}
            />
          {/if}
        </li>
      {/each}
    </ul>
  </PanelSection>

  {#if data.selectedCourse !== null}
    <section class="detail" aria-labelledby="register-detail-heading">
      <h2 id="register-detail-heading">
        {m.register_course_heading({ course: data.selectedCourse })}
      </h2>

      {#if detail === null || detail.target === null}
        <p class="notice error" role="status">{m.register_detail_error()}</p>
      {:else}
        <p class="status-line">
          <span class="status">{detail.target.status}</span>
          <span class="countdown">{countdownText}</span>
        </p>

        <h3>{m.register_groups_heading()}</h3>
        {#if detail.groups.length === 0}
          <p class="empty-body">{m.register_no_groups()}</p>
        {:else}
          <table>
            <thead>
              <tr>
                <th scope="col">{m.register_group()}</th>
                <th scope="col">{m.register_day()}</th>
                <th scope="col">{m.register_time()}</th>
                <th scope="col">{m.register_capacity()}</th>
                <th scope="col">{m.register_status()}</th>
              </tr>
            </thead>
            <tbody>
              {#each detail.groups as group (group.group_id)}
                <tr>
                  <th scope="row">{group.name}</th>
                  <td>{group.day}</td>
                  <td>{group.time_start}–{group.time_end}</td>
                  <td
                    >{m.register_capacity_value({
                      capacity: group.capacity,
                      enrolled: group.enrolled,
                    })}</td
                  >
                  <td>{group.status}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if available.length > 0}
          <h3>{m.register_submit_heading()}</h3>
          <!--
            One form per group, and the button says exactly which place it
            takes. The legacy page put a confirmation dialog in front of this;
            a labelled button that names the group, its slot and its remaining
            capacity carries the same information and survives a browser with
            no JavaScript, which the dialog did not.
          -->
          <ul class="register-actions">
            {#each available as group (group.group_id)}
              <li>
                <form method="post" action="?/register">
                  <input
                    type="hidden"
                    name="course_number"
                    value={detail.courseNumber}
                  />
                  <input type="hidden" name="group_id" value={group.group_id} />
                  <button class="primary" type="submit">
                    {m.register_submit({
                      capacity: group.capacity,
                      day: group.day,
                      enrolled: group.enrolled,
                      group: group.name,
                      time: `${group.time_start}–${group.time_end}`,
                    })}
                  </button>
                </form>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="empty-body">{m.register_no_open_groups()}</p>
        {/if}

        <h3>{m.register_exams_heading()}</h3>
        {#if detail.exams.length === 0}
          <p class="empty-body">{m.register_no_exams()}</p>
        {:else}
          <ul class="exams">
            {#each detail.exams as exam (exam.exam_id)}
              <li>
                <span class="exam-title">{exam.title}</span>
                {#if exam.date_start}<span class="exam-date">{exam.date_start}</span>{/if}
                <span class="exam-mode">{exam.mode}</span>
              </li>
            {/each}
          </ul>
        {/if}
      {/if}
    </section>
  {/if}
{/if}

<style>
  .favorites,
  .flags,
  .register-actions,
  .exams {
    display: grid;
    min-width: 0;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .favorites {
    gap: 0.75rem;
  }

  .favorite {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.4rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-raised);
    padding: 0.8rem;
  }

  .favorite.selected {
    border-color: var(--accent-strong);
  }

  .favorite-head {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.5rem;
  }

  .flags {
    grid-auto-flow: row;
    color: var(--muted);
    font-size: 0.85rem;
  }

  h2,
  h3 {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  h3 {
    font-size: 0.95rem;
    margin-top: 0.5rem;
  }

  .number,
  .countdown,
  .notice,
  .empty-body,
  .empty-title,
  .status-line {
    overflow-wrap: anywhere;
  }

  .number,
  .countdown,
  .notice,
  .empty-body {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .notice {
    margin: 0 0 0.75rem;
    font-size: 1rem;
  }

  .notice.error {
    color: var(--danger);
  }

  .state,
  .detail {
    display: grid;
    max-width: 52rem;
    min-width: 0;
    justify-items: start;
    gap: 0.6rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    padding: 1rem;
    margin-top: 1rem;
  }

  .state p,
  .detail p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .status-line {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .status {
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-size: 0.78rem;
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

  table {
    width: 100%;
    min-width: 0;
    border-collapse: collapse;
    font-size: 0.85rem;
    table-layout: fixed;
  }

  th,
  td {
    border-bottom: 1px solid var(--border);
    padding: 0.35rem 0.25rem;
    text-align: start;
    overflow-wrap: anywhere;
  }

  thead th {
    color: var(--muted);
    font-weight: 700;
  }

  tbody th {
    font-weight: 400;
  }

  .exams li {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 0.5rem;
    overflow-wrap: anywhere;
  }

  .exam-date,
  .exam-mode {
    color: var(--muted);
    font-size: 0.85rem;
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

  button.primary,
  a.primary {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  a.primary {
    display: inline-flex;
    min-height: 2.75rem;
    align-items: center;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.5rem 0.9rem;
    text-decoration: none;
    overflow-wrap: anywhere;
  }
</style>
