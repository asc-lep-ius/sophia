import { describe, expect, it, vi } from "vitest";

import {
  startWebVitalsReporting,
  subscribeToWebVitals,
  toReport,
} from "../../src/lib/metrics/webVitals";

type Metric = {
  name: string;
  value: number;
  rating: string;
  navigationType?: string;
};

function reporterFor(metric: Metric) {
  return (handler: (value: Metric) => void) => handler(metric);
}

describe("web vitals reporting", () => {
  it("does nothing outside the browser", async () => {
    const loadReporters = vi.fn(async () => []);
    const send = vi.fn(async () => undefined);

    await subscribeToWebVitals({ isBrowser: false, loadReporters, send });

    expect(loadReporters).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  it("sends each field measurement in the contract's shape", async () => {
    const sent: unknown[] = [];

    await subscribeToWebVitals({
      isBrowser: true,
      loadReporters: async () => [
        reporterFor({
          name: "INP",
          value: 187.456,
          rating: "needs-improvement",
          navigationType: "navigate",
        }),
      ],
      send: async (report) => {
        sent.push(report);
      },
    });

    expect(sent).toEqual([
      {
        metric_name: "INP",
        rating: "needs_improvement",
        value: 187.456,
        navigation_type: "navigate",
      },
    ]);
  });

  it("translates the library's hyphenated rating to the API's", () => {
    expect(
      toReport({ name: "LCP", value: 1, rating: "needs-improvement" })?.rating,
    ).toBe("needs_improvement");
    expect(toReport({ name: "CLS", value: 0.01, rating: "good" })?.rating).toBe(
      "good",
    );
  });

  it("drops a metric the API's closed label set does not name", () => {
    expect(toReport({ name: "Custom", value: 1, rating: "good" })).toBeNull();
    expect(toReport({ name: "INP", value: 1, rating: "unknown" })).toBeNull();
  });

  it("never lets a failed report reach the learner", async () => {
    await expect(
      subscribeToWebVitals({
        isBrowser: true,
        loadReporters: async () => {
          throw new Error("chunk unavailable");
        },
      }),
    ).resolves.toBeUndefined();

    await expect(
      subscribeToWebVitals({
        isBrowser: true,
        loadReporters: async () => [
          reporterFor({ name: "INP", value: 12, rating: "good" }),
        ],
        send: async () => {
          throw new Error("endpoint unavailable");
        },
      }),
    ).resolves.toBeUndefined();
  });

  it("starts without blocking rendering", () => {
    const result = startWebVitalsReporting({
      isBrowser: true,
      loadReporters: async () => [],
      send: async () => undefined,
    });

    expect(result).toBeUndefined();
  });
});
