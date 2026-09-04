import { browser } from "$app/environment";
import { createApiClient, unwrapApiResponse } from "$lib/api/client";
import type { components } from "$lib/api/schema";

type WebVitalsReport = components["schemas"]["WebVitalsReportRequest"];
type MetricName = WebVitalsReport["metric_name"];
type Rating = WebVitalsReport["rating"];

type MetricHandler = (metric: {
  name: string;
  value: number;
  rating: string;
  navigationType?: string;
}) => void;

type Subscribe = (handler: MetricHandler) => void;

export type WebVitalsDependencies = {
  isBrowser?: boolean;
  loadReporters?: () => Promise<Subscribe[]>;
  send?: (report: WebVitalsReport) => Promise<void>;
};

const REPORTED_METRICS: MetricName[] = ["CLS", "FCP", "INP", "LCP", "TTFB"];
const RATINGS: Record<string, Rating> = {
  good: "good",
  "needs-improvement": "needs_improvement",
  poor: "poor",
};

let reportingStarted = false;

/**
 * Report field responsiveness from real sessions.
 *
 * INP is the one that matters here: the study surface's whole promise is that
 * a keyboard flow stays responsive, and a throttled CI run on a fixture deck
 * proves that only for the machine it ran on. This is what says whether it
 * holds on the devices learners actually use.
 *
 * Every failure path is silent. Losing a measurement is not worth an error in
 * front of somebody who is trying to study.
 */
export function startWebVitalsReporting(
  dependencies: WebVitalsDependencies = {},
): void {
  const isBrowser = dependencies.isBrowser ?? browser;
  if (!isBrowser || reportingStarted) {
    return;
  }

  reportingStarted = true;
  void subscribeToWebVitals({ ...dependencies, isBrowser });
}

export async function subscribeToWebVitals(
  dependencies: WebVitalsDependencies = {},
): Promise<void> {
  const isBrowser = dependencies.isBrowser ?? browser;
  if (!isBrowser) {
    return;
  }

  const loadReporters = dependencies.loadReporters ?? loadWebVitalsReporters;
  const send = dependencies.send ?? postWebVitalsReport;

  try {
    const reporters = await loadReporters();
    for (const subscribe of reporters) {
      subscribe((metric) => {
        const report = toReport(metric);
        if (report) {
          void send(report).catch(() => undefined);
        }
      });
    }
  } catch {
    return;
  }
}

export function toReport(metric: {
  name: string;
  value: number;
  rating: string;
  navigationType?: string;
}): WebVitalsReport | null {
  const metricName = REPORTED_METRICS.find((name) => name === metric.name);
  const rating = RATINGS[metric.rating];
  if (!metricName || !rating) {
    return null;
  }

  return {
    metric_name: metricName,
    rating,
    // CLS is unitless and the rest are milliseconds; the server stores neither,
    // it buckets by rating, so rounding here only keeps the payload tidy.
    value: Math.max(Math.round(metric.value * 1000) / 1000, 0),
    navigation_type: metric.navigationType ?? null,
  };
}

async function loadWebVitalsReporters(): Promise<Subscribe[]> {
  const { onCLS, onFCP, onINP, onLCP, onTTFB } = await import("web-vitals");
  return [onCLS, onFCP, onINP, onLCP, onTTFB] as unknown as Subscribe[];
}

async function postWebVitalsReport(report: WebVitalsReport): Promise<void> {
  const client = createApiClient();
  await unwrapApiResponse(
    client.POST("/api/metrics/web-vitals", { body: report }),
  );
}
