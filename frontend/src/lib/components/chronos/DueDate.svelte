<script lang="ts">
  import { dueDistance, formatDueDate } from "$lib/chronos/deadlines";
  import { m } from "$lib/paraglide/messages.js";

  type Props = {
    dueAt: string;
    /** The server's instant, so the phrase does not depend on the browser clock. */
    now: string;
    locale: string;
  };

  let { dueAt, now, locale }: Props = $props();

  const distance = $derived(dueDistance(new Date(dueAt), new Date(now)));
  const relative = $derived.by(() => {
    const { days } = distance;
    if (days < 0) {
      return Math.abs(days) === 1
        ? m.chronos_due_overdue_one()
        : m.chronos_due_overdue({ days: Math.abs(days) });
    }
    if (days === 0) {
      return m.chronos_due_today();
    }
    return days === 1
      ? m.chronos_due_one_day()
      : m.chronos_due_days({ days });
  });
</script>

<!--
  Both readings, always together.

  The phrase is what a learner plans against and it comes from elapsed seconds,
  so it is the same sentence in every timezone. The absolute date beside it is
  the fact the phrase was derived from, printed in UTC and labelled as such —
  without it, "in 1 day" is unfalsifiable, and a learner in Vancouver has no
  way to see that the deadline they read as Tuesday is stored as Wednesday.
-->
<span class="due" data-urgency={distance.urgency}>
  <span class="relative">{relative}</span>
  <time datetime={dueAt} class="absolute"
    >{m.chronos_due_at({ date: formatDueDate(dueAt, locale) })}</time
  >
</span>

<style>
  .due {
    display: grid;
    min-width: 0;
    gap: 0.1rem;
  }

  .relative {
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .due[data-urgency="overdue"] .relative {
    color: var(--danger);
  }

  .absolute {
    color: var(--muted);
    font-size: 0.82rem;
    overflow-wrap: anywhere;
  }
</style>
