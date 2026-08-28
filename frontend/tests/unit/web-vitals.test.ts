import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  reserveWebVitalsEndpoint,
  startReservedWebVitals,
} from "../../src/lib/metrics/webVitals";

describe("reserved web-vitals helper", () => {
  it("skips work outside the browser", async () => {
    const importWebVitals = vi.fn(async () => ({}));
    const postReservedEndpoint = vi.fn(async () => undefined);

    await reserveWebVitalsEndpoint({
      importWebVitals,
      isBrowser: false,
      postReservedEndpoint,
    });

    expect(importWebVitals).not.toHaveBeenCalled();
    expect(postReservedEndpoint).not.toHaveBeenCalled();
  });

  it("loads web-vitals and posts only the reserved typed endpoint", async () => {
    const calls: string[] = [];

    await reserveWebVitalsEndpoint({
      importWebVitals: async () => {
        calls.push("import");
        return {};
      },
      isBrowser: true,
      postReservedEndpoint: async () => {
        calls.push("post");
      },
    });

    expect(calls).toEqual(["import", "post"]);
  });

  it("fails silently when import or reservation fails", async () => {
    await expect(
      reserveWebVitalsEndpoint({
        importWebVitals: async () => {
          throw new Error("chunk unavailable");
        },
        isBrowser: true,
        postReservedEndpoint: async () => {
          throw new Error("must not run after failed import");
        },
      }),
    ).resolves.toBeUndefined();

    await expect(
      reserveWebVitalsEndpoint({
        importWebVitals: async () => ({}),
        isBrowser: true,
        postReservedEndpoint: async () => {
          throw new Error("endpoint unavailable");
        },
      }),
    ).resolves.toBeUndefined();
  });

  it("starts the reservation without blocking rendering", () => {
    const result = startReservedWebVitals({
      importWebVitals: async () => ({}),
      isBrowser: true,
      postReservedEndpoint: async () => undefined,
    });

    expect(result).toBeUndefined();
  });

  it("keeps the endpoint call bodyless", () => {
    const helper = readFileSync(
      join(process.cwd(), "src/lib/metrics/webVitals.ts"),
      "utf8",
    );

    expect(helper).toContain('POST("/api/metrics/web-vitals")');
    expect(helper).not.toMatch(/body\s*:/);
  });
});
