import type { SearchResult } from "$lib/search/results";

export type SearchStatus = "idle" | "loading" | "ready" | "error";

export type SearchRun = (
  query: string,
  signal: AbortSignal,
) => Promise<SearchResult[]>;

export type SearchControllerOptions = {
  run: SearchRun;
  debounceMs?: number;
  minQueryLength?: number;
};

/**
 * How long the surface waits before asking the server anything.
 *
 * The legacy page used half a second and that is what a learner's typing was
 * tuned against. It is a usability measure and nothing more: it keeps a
 * six-keystroke word from being six searches, and it protects nobody. The
 * request the server has to survive is the one a script sends without ever
 * touching this timer, which is why `/api/search` validates and scopes every
 * call on its own side.
 */
export const SEARCH_DEBOUNCE_MS = 500;

/** Below this a query matches most of the corpus, so it is not worth sending. */
export const MIN_QUERY_LENGTH = 2;

/**
 * Live search over plain REST, with the two failure modes a debounce alone
 * leaves open.
 *
 * The first is a request nobody is waiting for any more: every run gets an
 * `AbortController` and the next one aborts it, so a slow search for "gra" is
 * cancelled the moment "graph" is scheduled rather than left to finish and
 * spend the connection.
 *
 * The second is subtler and is what the sequence number is for. Abort is not
 * instantaneous, and two in-flight requests can settle in either order: a
 * short query that the index answers slowly can land *after* the longer query
 * that replaced it, and the learner watches their results revert to an older
 * search as they type. Only the newest issued run may write results; anything
 * else is dropped even when it succeeded.
 */
export class SearchController {
  #query = $state("");
  #submitted = $state("");
  #results = $state<SearchResult[]>([]);
  #status = $state<SearchStatus>("idle");
  #issued = 0;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #inflight: AbortController | null = null;
  #options: SearchControllerOptions;

  constructor(options: SearchControllerOptions) {
    this.#options = options;
  }

  get query(): string {
    return this.#query;
  }

  /** The query the currently shown results answer; never the one being typed. */
  get submitted(): string {
    return this.#submitted;
  }

  get results(): SearchResult[] {
    return this.#results;
  }

  get status(): SearchStatus {
    return this.#status;
  }

  get isEmpty(): boolean {
    return this.#status === "ready" && this.#results.length === 0;
  }

  get debounceMs(): number {
    return this.#options.debounceMs ?? SEARCH_DEBOUNCE_MS;
  }

  /** Accept a keystroke. Schedules a run; never starts one synchronously. */
  setQuery(value: string): void {
    this.#query = value;
    this.#clearTimer();

    if (!this.#isSearchable(value)) {
      this.#abortInflight();
      this.#submitted = "";
      this.#results = [];
      this.#status = "idle";
      return;
    }

    this.#timer = setTimeout(() => {
      this.#timer = null;
      void this.#run(value);
    }, this.debounceMs);
  }

  /** Search now — what pressing Enter does, rather than waiting out the timer. */
  submit(): void {
    this.#clearTimer();
    if (this.#isSearchable(this.#query)) {
      void this.#run(this.#query);
    }
  }

  /** Drop a pending run and abandon one in flight; for component teardown. */
  dispose(): void {
    this.#clearTimer();
    this.#abortInflight();
  }

  #isSearchable(value: string): boolean {
    const minimum = this.#options.minQueryLength ?? MIN_QUERY_LENGTH;
    return value.trim().length >= minimum;
  }

  async #run(rawQuery: string): Promise<void> {
    const query = rawQuery.trim();
    this.#abortInflight();

    const controller = new AbortController();
    this.#inflight = controller;
    this.#issued += 1;
    const sequence = this.#issued;
    this.#status = "loading";

    try {
      const results = await this.#options.run(query, controller.signal);
      if (sequence !== this.#issued) {
        return;
      }
      this.#results = results;
      this.#submitted = query;
      this.#status = "ready";
    } catch {
      // An abort is not a failure the learner should be told about: it means
      // a newer search replaced this one, and that search owns the status.
      if (sequence !== this.#issued || controller.signal.aborted) {
        return;
      }
      this.#results = [];
      this.#submitted = query;
      this.#status = "error";
    } finally {
      if (this.#inflight === controller) {
        this.#inflight = null;
      }
    }
  }

  #clearTimer(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
  }

  #abortInflight(): void {
    this.#inflight?.abort();
    this.#inflight = null;
  }
}
