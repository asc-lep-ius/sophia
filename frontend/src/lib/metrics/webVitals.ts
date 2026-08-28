import { browser } from "$app/environment";
import { createApiClient, unwrapApiResponse } from "$lib/api/client";

type WebVitalsReservationDependencies = {
  importWebVitals?: () => Promise<unknown>;
  isBrowser?: boolean;
  postReservedEndpoint?: () => Promise<void>;
};

let reservationStarted = false;

export function startReservedWebVitals(
  dependencies: WebVitalsReservationDependencies = {},
): void {
  const isBrowser = dependencies.isBrowser ?? browser;
  if (!isBrowser || reservationStarted) {
    return;
  }

  reservationStarted = true;
  void reserveWebVitalsEndpoint({ ...dependencies, isBrowser });
}

export async function reserveWebVitalsEndpoint(
  dependencies: WebVitalsReservationDependencies = {},
): Promise<void> {
  const isBrowser = dependencies.isBrowser ?? browser;
  if (!isBrowser) {
    return;
  }

  const importWebVitals = dependencies.importWebVitals ?? loadWebVitals;
  const postReservedEndpoint =
    dependencies.postReservedEndpoint ?? postReservedWebVitalsEndpoint;

  try {
    await importWebVitals();
    await postReservedEndpoint();
  } catch {
    return;
  }
}

async function loadWebVitals(): Promise<void> {
  await import("web-vitals");
}

async function postReservedWebVitalsEndpoint(): Promise<void> {
  const client = createApiClient();
  await unwrapApiResponse(client.POST("/api/metrics/web-vitals"));
}
