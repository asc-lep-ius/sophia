export type StudyShortcut =
  | { action: "reveal" }
  | { action: "confidence"; level: 1 | 2 | 3 | 4 | 5 }
  | { action: "grade"; rating: 1 | 2 | 3 | 4 }
  | { action: "undo" }
  | { action: "pause" }
  | { action: "focus" }
  | { action: "help" };

const GRADE_KEYS: Record<string, 1 | 2 | 3 | 4> = {
  "1": 1,
  "2": 2,
  "3": 3,
  "4": 4,
};

/**
 * Guessing … Certain, on the row beneath the grade keys.
 *
 * Not the digits: Space and 1–4 keep their meaning, so a learner who presses
 * Reveal and then a grade key out of habit is not taken to have been sure.
 */
export const CONFIDENCE_KEYS = ["q", "w", "e", "r", "t"] as const;

/**
 * Map a keydown to a study action, or null when the key is not ours.
 *
 * Typing an answer must never grade a card, so every shortcut is ignored while
 * focus is in an editable field. That is also why the shortcuts are unmodified
 * single keys: they are cheap where they apply, and inert where the learner is
 * writing. Every one of them has a visible control as well — the keyboard is
 * the fast path, not the only path.
 */
export function resolveShortcut(
  event: Pick<
    KeyboardEvent,
    "key" | "altKey" | "ctrlKey" | "metaKey" | "shiftKey"
  >,
  options: { editing: boolean },
): StudyShortcut | null {
  if (options.editing || event.altKey || event.ctrlKey || event.metaKey) {
    return null;
  }

  const grade = GRADE_KEYS[event.key];
  if (grade) {
    return { action: "grade", rating: grade };
  }

  const key = event.key.toLowerCase();
  const confidence = CONFIDENCE_KEYS.indexOf(
    key as (typeof CONFIDENCE_KEYS)[number],
  );
  if (confidence >= 0) {
    return {
      action: "confidence",
      level: (confidence + 1) as 1 | 2 | 3 | 4 | 5,
    };
  }

  switch (key) {
    case " ":
      return { action: "reveal" };
    case "u":
      return { action: "undo" };
    case "p":
      return { action: "pause" };
    case "f":
      return { action: "focus" };
    case "?":
      return { action: "help" };
    default:
      return null;
  }
}

const EDITABLE_TAGS = new Set(["INPUT", "SELECT", "TEXTAREA"]);

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return EDITABLE_TAGS.has(target.tagName) || target.isContentEditable === true;
}
