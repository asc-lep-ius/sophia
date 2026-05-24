import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const routesDir = fileURLToPath(new URL("../src/routes", import.meta.url));
const offenders = [];

async function scan(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      await scan(path);
      continue;
    }
    if (!entry.name.endsWith(".server.ts")) {
      continue;
    }
    const content = await readFile(path, "utf8");
    if (/\bfetch\s*\(/.test(content) && !/apiFetch\s*\(/.test(content)) {
      offenders.push(path);
    }
  }
}

await scan(routesDir);

if (offenders.length) {
  throw new Error(
    `Server loads must use apiFetch(event, path, init): ${offenders.join(", ")}`,
  );
}
