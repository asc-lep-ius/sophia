/**
 * What a learner has written in a session and not yet handed in.
 *
 * Every step of the cycle is its own route, so a step change unmounts the
 * card store and the text in it; so does a reload. The spec requires answer
 * text to survive page-level retries, and a learner who steps back to check
 * something must find their answer where they left it.
 *
 * `sessionStorage` rather than `localStorage`: an unsubmitted answer is
 * working, not a record, and on a shared machine it should not outlive the tab
 * it was written in. Nothing is kept on the server until the learner submits.
 */
export type DraftStore = {
  read(key: string): string | null;
  write(key: string, value: string): void;
  clear(key: string): void;
};

const KEY_PREFIX = "sophia-study-draft";

const NO_DRAFTS: DraftStore = {
  read: () => null,
  write: () => undefined,
  clear: () => undefined,
};

/**
 * The drafts for one part of one session — a phase's cards, the reflection.
 *
 * Scoped because the anchor question is answered twice: a pre-test draft
 * offered back on the post-test would show the learner their earlier answer
 * at exactly the moment the comparison needs a fresh one.
 */
export function sessionDrafts(
  sessionId: number,
  scope: string,
  storage: Storage | null = tabStorage(),
): DraftStore {
  if (!storage) {
    return NO_DRAFTS;
  }
  const keyFor = (key: string) => `${KEY_PREFIX}:${sessionId}:${scope}:${key}`;
  return {
    read: (key) => storage.getItem(keyFor(key)),
    write: (key, value) =>
      keep(() =>
        value
          ? storage.setItem(keyFor(key), value)
          : storage.removeItem(keyFor(key)),
      ),
    clear: (key) => storage.removeItem(keyFor(key)),
  };
}

function tabStorage(): Storage | null {
  // No window during SSR, where there is nothing to restore into anyway.
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch (error) {
    // Blocked storage throws on access rather than returning null.
    if (error instanceof DOMException) {
      return null;
    }
    throw error;
  }
}

function keep(write: () => void): void {
  try {
    write();
  } catch (error) {
    // A full or blocked store costs the draft its life beyond this page, not
    // the answer: the text is still in the card, and still gets submitted.
    if (!(error instanceof DOMException)) {
      throw error;
    }
  }
}
