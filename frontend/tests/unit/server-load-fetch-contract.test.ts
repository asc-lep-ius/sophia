import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  findServerLoadFetchOffenders,
  validateServerLoadFetchContract,
} from "../../scripts/assert-server-load-fetch.mjs";

const tempDirs: string[] = [];

describe("server load fetch guard", () => {
  afterEach(async () => {
    await Promise.all(
      tempDirs.map((tempDir) => rm(tempDir, { recursive: true, force: true })),
    );
    tempDirs.length = 0;
  });

  it("allows dashboard server loads that call apiFetch with the event", () => {
    expect(
      validateServerLoadFetchContract([
        {
          path: "src/routes/dashboard/+page.server.ts",
          content:
            'export const load = async (event) => apiFetch(event, "/api/ready");\n',
        },
      ]),
    ).toEqual([]);
  });

  it("rejects mixed server loads that call apiFetch and raw fetch", () => {
    expect(
      validateServerLoadFetchContract([
        {
          path: "src/routes/dashboard/+page.server.ts",
          content: [
            'await apiFetch(event, "/api/ready");',
            'await fetch("/api/ready");',
          ].join("\n"),
        },
      ]),
    ).toEqual(["src/routes/dashboard/+page.server.ts"]);
  });

  it("finds raw fetch calls in nested server load files", async () => {
    const frontendRoot = await mkdtemp(
      join(tmpdir(), "sophia-server-fetch-contract-"),
    );
    tempDirs.push(frontendRoot);

    const routesDir = join(frontendRoot, "src/routes");
    await mkdir(join(routesDir, "dashboard"), { recursive: true });
    await mkdir(join(routesDir, "study"), { recursive: true });
    await writeFile(
      join(routesDir, "dashboard/+page.server.ts"),
      [
        'await apiFetch(event, "/api/ready");',
        'await event.fetch("/api/ready");',
      ].join("\n"),
    );
    await writeFile(
      join(routesDir, "study/+page.server.ts"),
      'await apiFetch(event, "/api/ready");\n',
    );

    const offenders = await findServerLoadFetchOffenders(routesDir);

    expect(offenders).toEqual([join(routesDir, "dashboard/+page.server.ts")]);
  });
});
