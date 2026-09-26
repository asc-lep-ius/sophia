import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { selectedLearningPathId } from "../../src/lib/learningPath";

const ROUTES_DIR = join(import.meta.dirname, "../../src/routes");

describe("selectedLearningPathId", () => {
  it("reads a numeric tenant id as the course id the API takes", () => {
    expect(selectedLearningPathId({ learning_path_id: "12" })).toBe(12);
  });

  it("reads an unselected tenant as null", () => {
    expect(selectedLearningPathId({ learning_path_id: null })).toBeNull();
  });

  it.each(["default-learning-path", "", "0", "-3", "1.5", " 12", "1e3"])(
    "never coerces %j into an id",
    (raw) => {
      expect(selectedLearningPathId({ learning_path_id: raw })).toBeNull();
    },
  );

  it("is the only way a route reads the tenant's learning path", () => {
    // #106: the same `Number(...)` guard was pasted into eight load functions,
    // and a second private copy into eight more, each turning an unselected
    // tenant into NaN on its own terms.
    const offenders = readdirSync(ROUTES_DIR, { recursive: true })
      .map(String)
      .filter((file) => file.endsWith(".ts"))
      .filter((file) => {
        const source = readFileSync(join(ROUTES_DIR, file), "utf8");
        return (
          source.includes("Number(event.locals.tenant.learning_path_id)") ||
          source.includes("function numericLearningPathId")
        );
      });

    expect(offenders).toEqual([]);
  });
});
