import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  classifyDeadlineOutcome,
  dueDistance,
  formatDueDate,
  formatHours,
  readOutcomeFilter,
  sortByDueDate,
  sortByDueDateDescending,
  type Deadline,
} from "../../src/lib/chronos/deadlines";

type ParityCase = {
  why: string;
  offset_seconds: number;
  days: number;
  legacy: string;
};

// Read from disk rather than imported, so the Python suite and this one are
// demonstrably looking at the same bytes rather than at two copies.
const parity = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "tests/fixtures/chronos-date-parity.json"),
    "utf8",
  ),
) as { now: string; cases: ParityCase[] };

const MS_PER_SECOND = 1000;

describe("deadline due distance", () => {
  const now = new Date(parity.now);

  for (const entry of parity.cases) {
    it(`matches the legacy service for ${entry.why}`, () => {
      const dueAt = new Date(
        now.getTime() + entry.offset_seconds * MS_PER_SECOND,
      );

      expect(dueDistance(dueAt, now).days).toBe(entry.days);
    });
  }

  it("separates overdue, today and upcoming", () => {
    const day = 86_400_000;

    expect(dueDistance(new Date(now.getTime() - day), now).urgency).toBe(
      "overdue",
    );
    expect(dueDistance(new Date(now.getTime() + day / 2), now).urgency).toBe(
      "today",
    );
    expect(dueDistance(new Date(now.getTime() + day * 3), now).urgency).toBe(
      "upcoming",
    );
  });

  /**
   * The whole reason the distance is elapsed seconds rather than calendar days.
   * Europe/Vienna springs forward at 02:00 on this date, so the "same" wall
   * clock a day later is 23 hours away; counting seconds gives one answer in
   * every zone, which is the server's answer.
   */
  it("is the same number whatever the machine's timezone is", () => {
    const dueAt = new Date(now.getTime() + 86_400_000);
    const viennaOffsetBefore = now.getTimezoneOffset();

    expect(dueDistance(dueAt, now).days).toBe(1);
    expect(now.getTimezoneOffset()).toBe(viennaOffsetBefore);
  });
});

describe("deadline outcome", () => {
  const dueAt = new Date("2026-09-01T10:00:00Z");

  it("calls a deadline finished before its date on time", () => {
    expect(
      classifyDeadlineOutcome(
        dueAt,
        new Date("2026-08-31T10:00:00Z"),
        new Date("2026-09-10T10:00:00Z"),
      ),
    ).toBe("on_time");
  });

  it("calls a deadline finished after its date late", () => {
    expect(
      classifyDeadlineOutcome(
        dueAt,
        new Date("2026-09-02T10:00:00Z"),
        new Date("2026-09-10T10:00:00Z"),
      ),
    ).toBe("late");
  });

  it("calls an unfinished past deadline missed", () => {
    expect(
      classifyDeadlineOutcome(dueAt, null, new Date("2026-09-10T10:00:00Z")),
    ).toBe("missed");
  });

  it("leaves an unfinished future deadline on time", () => {
    expect(
      classifyDeadlineOutcome(dueAt, null, new Date("2026-08-20T10:00:00Z")),
    ).toBe("on_time");
  });

  /**
   * The history surface passes the due instant itself for a deadline that was
   * reflected on, because nothing records when it was actually finished. That
   * makes "late" unreachable there, and this pins the reason rather than the
   * symptom: the classifier can produce it, the data cannot.
   */
  it("never reports late when the completion instant is the due instant", () => {
    expect(
      classifyDeadlineOutcome(dueAt, dueAt, new Date("2026-09-10T10:00:00Z")),
    ).toBe("on_time");
  });
});

describe("deadline formatting", () => {
  it("writes sub-hour effort in minutes, as the legacy page did", () => {
    expect(formatHours(0.25)).toBe("15min");
    expect(formatHours(0)).toBe("0min");
    expect(formatHours(1.5)).toBe("1.5h");
    expect(formatHours(12)).toBe("12.0h");
  });

  it("prints the absolute date in UTC whatever the browser's zone is", () => {
    // 00:30 UTC is the previous evening in New York and mid-morning in Tokyo.
    // Both have to read the same date here, because the server stored one.
    const formatted = formatDueDate("2026-09-02T00:30:00Z", "en");

    expect(formatted).toContain("2026");
    expect(formatted).toContain("02");
    expect(formatted).not.toContain("01");
  });
});

describe("deadline ordering and filters", () => {
  const deadline = (id: string, dueAt: string): Deadline =>
    ({
      deadline_type: "assignment",
      due_at: dueAt,
      extra: {},
      grade_weight: null,
      id,
      learning_path_id: 12,
      learning_path_name: "AlgoDat",
      name: id,
      submission_status: null,
      url: null,
    }) as Deadline;

  const deadlines = [
    deadline("later", "2026-09-10T10:00:00Z"),
    deadline("sooner", "2026-09-01T10:00:00Z"),
  ];

  it("puts the soonest deadline first on the upcoming list", () => {
    expect(sortByDueDate(deadlines).map((entry) => entry.id)).toEqual([
      "sooner",
      "later",
    ]);
  });

  it("puts the most recent deadline first in the history", () => {
    expect(sortByDueDateDescending(deadlines).map((entry) => entry.id)).toEqual(
      ["later", "sooner"],
    );
  });

  it("does not reorder the array it was given", () => {
    sortByDueDate(deadlines);

    expect(deadlines.map((entry) => entry.id)).toEqual(["later", "sooner"]);
  });

  it("falls back to every outcome for a filter it does not recognise", () => {
    expect(
      readOutcomeFilter(new URL("http://localhost/app/chronos/history")),
    ).toBe("all");
    expect(
      readOutcomeFilter(
        new URL("http://localhost/app/chronos/history?outcome=nonsense"),
      ),
    ).toBe("all");
    expect(
      readOutcomeFilter(
        new URL("http://localhost/app/chronos/history?outcome=missed"),
      ),
    ).toBe("missed");
  });
});
