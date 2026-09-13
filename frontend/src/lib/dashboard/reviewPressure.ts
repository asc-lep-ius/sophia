import type { ReviewItem } from "$lib/dashboard/panels";

export type PressureBucket = {
  /** Whole days from `now`; 0 is today. */
  dayOffset: number;
  count: number;
};

const MS_PER_DAY = 86_400_000;

/** How far ahead the review pressure figure looks. */
export const PRESSURE_DAYS = 7;

/**
 * How many reviews land on each of the next `days` days.
 *
 * `now` is a parameter rather than a call to `Date.now()` so the buckets are a
 * pure function of their input: the figure they feed has to render the same
 * way on the server and in the browser, and a test has to be able to state
 * what "today" is. Anything already overdue counts against today, because
 * that is the day the learner has to deal with it.
 */
export function reviewPressure(
  reviews: ReviewItem[],
  options: { now: Date; days: number },
): PressureBucket[] {
  const buckets = Array.from(
    { length: Math.max(options.days, 0) },
    (_, dayOffset) => ({
      dayOffset,
      count: 0,
    }),
  );
  const startOfToday = startOfDay(options.now);

  for (const review of reviews) {
    const due = new Date(review.next_review_at);
    if (Number.isNaN(due.valueOf())) {
      continue;
    }
    const offset = Math.max(
      Math.floor((startOfDay(due).valueOf() - startOfToday) / MS_PER_DAY),
      0,
    );
    const bucket = buckets[offset];
    if (bucket) {
      bucket.count += 1;
    }
  }

  return buckets;
}

function startOfDay(value: Date): number {
  return new Date(
    value.getFullYear(),
    value.getMonth(),
    value.getDate(),
  ).valueOf();
}
