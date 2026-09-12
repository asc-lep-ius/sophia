<script lang="ts">
  import { resolve } from "$app/paths";
  import BarFigure from "$lib/components/dashboard/BarFigure.svelte";
  import CalibrationFigure from "$lib/components/dashboard/CalibrationFigure.svelte";
  import PanelSection from "$lib/components/dashboard/PanelSection.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { barRow, splitCalibrationRows, type FigureDatum } from "$lib/dashboard/figures";
  import { nextAction } from "$lib/dashboard/nextAction";
  import { m } from "$lib/paraglide/messages.js";
  import type { PageData } from "./$types";

  type Props = { data: PageData };

  let { data }: Props = $props();

  const CALIBRATION_ROW_LIMIT = 6;
  const DUE_TOPIC_LIMIT = 5;

  const dueReviews = $derived(data.due.data.filter((review) => review.is_due));

  const action = $derived(
    nextAction({
      dueReviewCount: dueReviews.length,
      sessions: data.sessions.data,
    }),
  );

  const pressureBars = $derived(
    barRow(
      data.pressure.map(
        (bucket): FigureDatum => ({
          display: String(bucket.count),
          key: `day-${bucket.dayOffset}`,
          label: dayLabel(bucket.dayOffset),
          value: bucket.count,
        }),
      ),
    ),
  );

  const pressureTotal = $derived(
    data.pressure.reduce((total, bucket) => total + bucket.count, 0),
  );

  const calibration = $derived(
    splitCalibrationRows(
      data.calibration.data.map((rating) => ({
        actual: rating.actual,
        legacyScored: rating.legacy_scored,
        predicted: rating.predicted,
        topic: rating.topic,
      })),
    ),
  );

  const calibrationRows = $derived(calibration.measured.slice(0, CALIBRATION_ROW_LIMIT));

  const calibrationNote = $derived(
    calibration.legacyScored.length > 0
      ? m.dashboard_calibration_legacy_excluded({
          count: calibration.legacyScored.length,
        })
      : undefined,
  );

  function dayLabel(dayOffset: number): string {
    if (dayOffset === 0) {
      return m.dashboard_pressure_today();
    }
    return m.dashboard_pressure_in_days({ days: dayOffset });
  }
</script>

<PageHeader heading={m.dashboard_heading()} summary={m.dashboard_summary()} />

{#if data.learningPathId === null}
  <p class="notice">{m.dashboard_no_learning_path()}</p>
{:else}
  <!--
    First, above everything: a dashboard that ranks nothing hands the ranking
    back to the learner, which is the decision they opened it to have made.
  -->
  <section class="next-action" aria-labelledby="dashboard-next-action-heading">
    <h2 id="dashboard-next-action-heading">{m.dashboard_next_action_heading()}</h2>
    {#if action.kind === "review"}
      <p>{m.dashboard_next_action_review({ count: action.count })}</p>
      <a class="primary" href={resolve("/review", {})}>{m.dashboard_open_review()}</a>
    {:else if action.kind === "resume"}
      <p>{m.dashboard_next_action_resume({ topic: action.topic })}</p>
      <a
        class="primary"
        href={resolve("/study/[sessionId]/act", {
          sessionId: String(action.sessionId),
        })}
      >
        {m.dashboard_open_session()}
      </a>
    {:else if action.kind === "quickstart"}
      <p>{m.dashboard_next_action_quickstart()}</p>
      <a class="primary" href={resolve("/quickstart", {})}>{m.dashboard_open_quickstart()}</a>
    {:else}
      <p>{m.dashboard_next_action_study()}</p>
      <a class="primary" href={resolve("/study", {})}>{m.dashboard_open_study()}</a>
    {/if}
  </section>

  <div class="panel-grid">
    <PanelSection
      id="dashboard-due"
      heading={m.dashboard_due_heading()}
      status={data.due.status}
      isEmpty={dueReviews.length === 0}
    >
      {#snippet empty()}
        <div class="empty-state">
          <p class="empty-title">{m.dashboard_due_empty_title()}</p>
          <p class="empty-body">{m.dashboard_due_empty_body()}</p>
          <a href={resolve("/study", {})}>{m.dashboard_open_study()}</a>
        </div>
      {/snippet}
      <p class="count">{m.dashboard_due_count({ count: dueReviews.length })}</p>
      <ul class="topic-list">
        {#each dueReviews.slice(0, DUE_TOPIC_LIMIT) as review (review.topic)}
          <li>{review.topic}</li>
        {/each}
      </ul>
      <a class="primary" href={resolve("/review", {})}>{m.dashboard_open_review()}</a>
    </PanelSection>

    <PanelSection
      id="dashboard-pressure"
      heading={m.dashboard_pressure_heading()}
      status={data.upcoming.status}
      isEmpty={pressureTotal === 0}
    >
      {#snippet empty()}
        <div class="empty-state">
          <p class="empty-title">{m.dashboard_pressure_empty_title()}</p>
          <p class="empty-body">{m.dashboard_pressure_empty_body()}</p>
        </div>
      {/snippet}
      <BarFigure
        id="dashboard-pressure-figure"
        bars={pressureBars}
        caption={m.dashboard_pressure_caption()}
        labelHeading={m.dashboard_pressure_day()}
        summary={m.dashboard_pressure_summary({ count: pressureTotal })}
        valueHeading={m.dashboard_pressure_count()}
      />
    </PanelSection>

    <PanelSection
      id="dashboard-calibration"
      heading={m.dashboard_calibration_heading()}
      note={calibrationNote}
      status={data.calibration.status}
      isEmpty={calibrationRows.length === 0}
    >
      {#snippet empty()}
        <div class="empty-state">
          <p class="empty-title">{m.dashboard_calibration_empty_title()}</p>
          <p class="empty-body">{m.dashboard_calibration_empty_body()}</p>
          {#if calibration.unmeasured.length > 0}
            <p class="empty-body">
              {m.dashboard_calibration_unmeasured({
                count: calibration.unmeasured.length,
              })}
            </p>
          {/if}
        </div>
      {/snippet}
      <CalibrationFigure id="dashboard-calibration-figure" rows={calibrationRows} />
      {#if calibration.unmeasured.length > 0}
        <p class="count">
          {m.dashboard_calibration_unmeasured({
            count: calibration.unmeasured.length,
          })}
        </p>
      {/if}
    </PanelSection>

    <PanelSection
      id="dashboard-sessions"
      heading={m.dashboard_sessions_heading()}
      status={data.sessions.status}
      isEmpty={data.sessions.data.length === 0}
    >
      {#snippet empty()}
        <div class="empty-state">
          <p class="empty-title">{m.dashboard_sessions_empty_title()}</p>
          <p class="empty-body">{m.dashboard_sessions_empty_body()}</p>
          <a href={resolve("/quickstart", {})}>{m.dashboard_open_quickstart()}</a>
        </div>
      {/snippet}
      <ul class="session-list">
        {#each data.sessions.data.slice(0, DUE_TOPIC_LIMIT) as session (session.id)}
          <li>
            <span class="session-topic">{session.topic}</span>
            <span class="session-state">
              {session.completed_at
                ? m.study_session_completed()
                : m.study_session_in_progress()}
            </span>
          </li>
        {/each}
      </ul>
    </PanelSection>
  </div>
{/if}

<style>
  .next-action {
    display: grid;
    min-width: 0;
    justify-items: start;
    gap: 0.6rem;
    margin-bottom: 1rem;
    border: 1px solid var(--accent-strong);
    border-radius: 8px;
    background: var(--accent-soft);
    padding: 1rem;
  }

  .next-action h2 {
    margin: 0;
    font-size: 1.05rem;
    overflow-wrap: anywhere;
  }

  .next-action p,
  .notice,
  .count,
  .empty-title,
  .empty-body {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .notice,
  .empty-body,
  .session-state {
    color: var(--muted);
    font-size: 0.9rem;
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

  .panel-grid {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(auto-fit, minmax(min(22rem, 100%), 1fr));
    gap: 0.9rem;
  }

  .count {
    font-size: 1.5rem;
    font-weight: 700;
  }

  .topic-list,
  .session-list {
    display: grid;
    gap: 0.3rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .topic-list li,
  .session-list li {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.4rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.3rem;
    overflow-wrap: anywhere;
  }

  .session-topic {
    min-width: 0;
    overflow-wrap: anywhere;
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
    color: #ffffff;
  }
</style>
