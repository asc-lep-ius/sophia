import { apiFetch } from "../../hooks.server";
import type { PageServerLoad } from "./$types";

type ReadyStatus = "ready" | "not_ready" | "unknown";

export const load: PageServerLoad = async (event) => ({
  apiReady: await loadApiReadyStatus(event),
});

async function loadApiReadyStatus(
  event: Parameters<typeof apiFetch>[0],
): Promise<ReadyStatus> {
  try {
    const response = await apiFetch(event, "/api/ready");
    if (!response.ok) {
      return "not_ready";
    }

    const body = await response.json();
    return isReadyBody(body) && body.status === "ready" ? "ready" : "not_ready";
  } catch {
    return "unknown";
  }
}

function isReadyBody(value: unknown): value is { status: ReadyStatus } {
  if (!value || typeof value !== "object") {
    return false;
  }

  const status = (value as { status?: unknown }).status;
  return status === "ready" || status === "not_ready";
}
