import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import CalibrationPage from "../../src/routes/calibration/+page.svelte";
import { load } from "../../src/routes/calibration/+page.server";
import {
  MIN_MEASURED_FOR_READING,
  calibrationView,
} from "../../src/lib/calibration/insights";
import type { CardConfidence } from "../../src/lib/calibration/cardConfidence";
import type { CalibrationRating, Panel } from "../../src/lib/dashboard/panels";
import {
  createLoadEvent,
  jsonResponse,
  layoutData,
} from "./support/request-event";

const CALIBRATION_URL = "http://localhost/app/calibration";

describe("calibration view", () => {
  it("keeps rows the retired scorer touched out of the figure", () => {
    const view = calibrationView([
      rating("Graphs", 0.9, 0.4),
      rating("Hashing", 0.8, 1, { legacyScored: true }),
    ]);

    expect(view.measured.map((row) => row.topic)).toEqual(["Graphs"]);
    expect(view.legacyScoredCount).toBe(1);
  });

  it("counts a prediction with no measurement instead of drawing it as zero", () => {
    const view = calibrationView([rating("Kombinatorik", 0.7, null)]);

    expect(view.measured).toEqual([]);
    expect(view.unmeasuredCount).toBe(1);
  });

  /**
   * The threshold lives on the server. If the page decided for itself which
   * topics counted as blind spots, a learner could be told a topic is one here
   * while the table below shows it as fine.
   */
  it("takes the blind-spot verdict from the server, never from the gap", () => {
    const view = calibrationView([
      rating("Graphs", 0.9, 0.2, { blindSpot: false }),
      rating("Sorting", 0.6, 0.5, { blindSpot: true }),
    ]);

    expect(view.blindSpots.map((spot) => spot.topic)).toEqual(["Sorting"]);
  });

  it("never flags a topic the retired scorer measured", () => {
    const view = calibrationView([
      rating("Hashing", 0.9, 1, { blindSpot: true, legacyScored: true }),
    ]);

    expect(view.blindSpots).toEqual([]);
  });

  it("orders blind spots worst overshoot first", () => {
    const view = calibrationView([
      rating("Graphs", 0.7, 0.4, { blindSpot: true }),
      rating("Sorting", 0.9, 0.1, { blindSpot: true }),
    ]);

    expect(view.blindSpots.map((spot) => spot.topic)).toEqual([
      "Sorting",
      "Graphs",
    ]);
    expect(view.blindSpots[0]?.gapPercent).toBe(80);
  });

  it("withholds a reading until there is enough measured to be one", () => {
    const rows = Array.from({ length: MIN_MEASURED_FOR_READING - 1 }, (_x, i) =>
      rating(`Topic ${i}`, 0.8, 0.5),
    );

    expect(calibrationView(rows).hasReading).toBe(false);
    expect(
      calibrationView([...rows, rating("One more", 0.8, 0.5)]).hasReading,
    ).toBe(true);
  });
});

describe("calibration server load", () => {
  it("asks for the ratings once and never for blind spots, so the page cannot contradict itself", async () => {
    const fetch = vi.fn(fetchFixture());

    await load(createLoadEvent({ fetch, url: CALIBRATION_URL }) as never);

    expect(fetch.mock.calls.map((call) => String(call[0]))).toEqual([
      "/api/calibration/ratings?learning_path_id=12",
      "/api/calibration/card-confidence?learning_path_id=12",
    ]);
  });

  it("reads the per-card counts the server returns", async () => {
    const fetch = vi.fn(fetchFixture());

    const data = (await load(
      createLoadEvent({ fetch, url: CALIBRATION_URL }) as never,
    )) as CalibrationData;

    expect(data.cardConfidence).toEqual({
      status: "ready",
      data: {
        topics: [{ topic: "Graphs", rated: 4, sure: 3, sure_again: 2 }],
        unrated: 2,
      },
    });
  });

  it("scopes the request on the session tenant, not on the query string", async () => {
    const fetch = vi.fn(fetchFixture());

    await load(
      createLoadEvent({
        fetch,
        url: `${CALIBRATION_URL}?learning_path_id=99`,
      }) as never,
    );

    expect(fetch.mock.calls.map((call) => String(call[0]))).not.toContain(
      "/api/calibration/ratings?learning_path_id=99",
    );
  });

  it("reports a failed call rather than an empty calibration", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 500 }));

    const data = (await load(
      createLoadEvent({ fetch, url: CALIBRATION_URL }) as never,
    )) as CalibrationData;

    expect(data.ratings.status).toBe("error");
    expect(data.cardConfidence.status).toBe("error");
  });

  it("sends an unauthenticated visitor to sign in", async () => {
    await expect(
      load(
        createLoadEvent({
          authenticated: false,
          fetch: vi.fn(),
          url: CALIBRATION_URL,
        }) as never,
      ),
    ).rejects.toMatchObject({ location: "/app/login", status: 303 });
  });
});

describe("calibration page, per card", () => {
  it("shows per topic how often a sure answer met Again", () => {
    render(CalibrationPage, {
      data: pageData({
        cardConfidence: {
          data: {
            topics: [
              { topic: "Graphs", rated: 4, sure: 3, sure_again: 2 },
              { topic: "Trees", rated: 2, sure: 0, sure_again: 0 },
            ],
            unrated: 0,
          },
          status: "ready",
        },
      }),
    });

    const panel = screen.getByRole("region", { name: "When you were sure" });
    const rows = within(panel).getAllByRole("listitem");
    expect(
      rows.map((row) => row.textContent?.replace(/\s+/g, " ").trim()),
    ).toEqual([
      "Graphs 2 of 3 sure answers graded Again",
      "Trees Not sure of any of 2 rated answers",
    ]);
    expect(
      within(panel).getByText(
        "Counts only answers rated for confidence before their reveal.",
      ),
    ).toBeTruthy();
  });

  it("says how many earlier answers carry no confidence and are left out", () => {
    render(CalibrationPage, {
      data: pageData({
        cardConfidence: {
          data: {
            topics: [{ topic: "Graphs", rated: 1, sure: 1, sure_again: 1 }],
            unrated: 7,
          },
          status: "ready",
        },
      }),
    });

    expect(
      screen.getByText(/7 earlier answers carry no rating and are left out/),
    ).toBeTruthy();
  });

  it("says what will appear when no answer carries a confidence yet", () => {
    render(CalibrationPage, {
      data: pageData({
        cardConfidence: {
          data: { topics: [], unrated: 5 },
          status: "ready",
        },
      }),
    });

    const panel = screen.getByRole("region", { name: "When you were sure" });
    expect(
      within(panel).getByText(/No answer carries a confidence yet/),
    ).toBeTruthy();
    expect(within(panel).getByText(/5 earlier answers/)).toBeTruthy();
  });
});

describe("calibration page", () => {
  it("declares the rows it left out instead of dropping them silently", () => {
    render(CalibrationPage, {
      data: pageData({
        ratings: {
          data: [
            rating("Graphs", 0.9, 0.4),
            rating("Hashing", 0.8, 1, { legacyScored: true }),
            rating("Kombinatorik", 0.7, null),
          ],
          status: "ready",
        },
      }),
    });

    expect(screen.getByText(/retired scorer/)).toBeTruthy();
    expect(screen.getByText(/no measurement yet/)).toBeTruthy();
  });

  it("says how few measurements a sparse reading rests on", () => {
    render(CalibrationPage, {
      data: pageData({
        ratings: { data: [rating("Graphs", 0.9, 0.4)], status: "ready" },
      }),
    });

    expect(screen.getByText(/too few to read a pattern from/)).toBeTruthy();
  });

  it("says nothing about a pattern once there is enough to read one", () => {
    render(CalibrationPage, {
      data: pageData({
        ratings: {
          data: [
            rating("A", 0.9, 0.4),
            rating("B", 0.8, 0.5),
            rating("C", 0.7, 0.6),
          ],
          status: "ready",
        },
      }),
    });

    expect(screen.queryByText(/too few to read a pattern from/)).toBeNull();
    expect(screen.getByText("Based on 3 measured topics.")).toBeTruthy();
  });

  it("separates nothing measured from nothing flagged", () => {
    render(CalibrationPage, {
      data: pageData({
        ratings: { data: [rating("Kombinatorik", 0.7, null)], status: "ready" },
      }),
    });
    expect(screen.getByText(/Nothing is measured yet/)).toBeTruthy();

    render(CalibrationPage, {
      data: pageData({
        ratings: { data: [rating("Graphs", 0.9, 0.9)], status: "ready" },
      }),
    });
    expect(
      screen.getAllByText("No topic is flagged as a blind spot.").length,
    ).toBeGreaterThan(0);
  });

  it("offers the next action when there is nothing to calibrate against", () => {
    render(CalibrationPage, { data: pageData({}) });

    const panel = screen.getByRole("region", {
      name: "Predicted against measured",
    });
    expect(within(panel).getByText("No calibration data yet")).toBeTruthy();
  });

  it("says the panel is outside the account's scope rather than showing it empty", () => {
    render(CalibrationPage, {
      data: pageData({ ratings: { data: [], status: "unauthorized" } }),
    });

    const panel = screen.getByRole("region", {
      name: "Predicted against measured",
    });
    expect(
      within(panel).getByText(/outside what your account may read/),
    ).toBeTruthy();
  });
});

type CalibrationData = {
  learningPathId: number | null;
  ratings: Panel<CalibrationRating[]>;
  cardConfidence: Panel<CardConfidence>;
};

function pageData(overrides: Partial<CalibrationData>) {
  return {
    ...layoutData,
    learningPathId: 12,
    ratings: { data: [], status: "ready" } as Panel<CalibrationRating[]>,
    cardConfidence: {
      data: { topics: [], unrated: 0 },
      status: "ready",
    } as Panel<CardConfidence>,
    ...overrides,
  };
}

function rating(
  topic: string,
  predicted: number,
  actual: number | null,
  options: { blindSpot?: boolean; legacyScored?: boolean } = {},
): CalibrationRating {
  return {
    actual,
    calibration_error: actual === null ? null : predicted - actual,
    difficulty_level: "transfer",
    is_blind_spot: options.blindSpot ?? false,
    learning_path_id: 12,
    legacy_scored: options.legacyScored ?? false,
    predicted,
    rated_at: "2026-09-04T10:00:00Z",
    topic,
  };
}

function fetchFixture() {
  return async (url: string | URL): Promise<Response> => {
    if (String(url).includes("/api/calibration/card-confidence")) {
      return jsonResponse({
        learning_path_id: 12,
        topics: [{ topic: "Graphs", rated: 4, sure: 3, sure_again: 2 }],
        unrated: 2,
      });
    }
    return String(url).includes("/api/calibration/ratings")
      ? jsonResponse({
          learning_path_id: 12,
          ratings: [rating("Graphs", 0.9, 0.4)],
        })
      : jsonResponse({});
  };
}
