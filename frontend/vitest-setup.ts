import "@testing-library/svelte/vitest";
import { afterEach } from "vitest";

// Study runtimes keep answer drafts in sessionStorage by default; one test's
// draft must not turn up as the next test's answer. Node-environment files
// have no storage to clear.
afterEach(() => globalThis.sessionStorage?.clear());
