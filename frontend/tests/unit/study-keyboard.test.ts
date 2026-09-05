import { describe, expect, it } from "vitest";

import {
  isEditableTarget,
  resolveShortcut,
} from "../../src/lib/study/keyboard";

function keydown(key: string, modifiers: Partial<KeyboardEvent> = {}) {
  return {
    key,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    ...modifiers,
  };
}

describe("study keyboard shortcuts", () => {
  it("maps the grade keys to the same scale the server grades on", () => {
    expect(resolveShortcut(keydown("1"), { editing: false })).toEqual({
      action: "grade",
      rating: 1,
    });
    expect(resolveShortcut(keydown("4"), { editing: false })).toEqual({
      action: "grade",
      rating: 4,
    });
  });

  it("maps the session controls", () => {
    expect(resolveShortcut(keydown(" "), { editing: false })).toEqual({
      action: "reveal",
    });
    expect(resolveShortcut(keydown("u"), { editing: false })).toEqual({
      action: "undo",
    });
    expect(resolveShortcut(keydown("P"), { editing: false })).toEqual({
      action: "pause",
    });
    expect(resolveShortcut(keydown("f"), { editing: false })).toEqual({
      action: "focus",
    });
    expect(resolveShortcut(keydown("?"), { editing: false })).toEqual({
      action: "help",
    });
  });

  it("stays inert while the learner is writing an answer", () => {
    expect(resolveShortcut(keydown("1"), { editing: true })).toBeNull();
    expect(resolveShortcut(keydown(" "), { editing: true })).toBeNull();
  });

  it("leaves modified keys to the browser and the app shell", () => {
    expect(
      resolveShortcut(keydown("k", { ctrlKey: true }), { editing: false }),
    ).toBeNull();
    expect(
      resolveShortcut(keydown("1", { metaKey: true }), { editing: false }),
    ).toBeNull();
  });

  it("ignores keys it does not own", () => {
    expect(resolveShortcut(keydown("x"), { editing: false })).toBeNull();
    expect(resolveShortcut(keydown("5"), { editing: false })).toBeNull();
  });

  it("recognises the fields a shortcut must not fire inside", () => {
    const textarea = document.createElement("textarea");
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    const heading = document.createElement("h1");

    expect(isEditableTarget(textarea)).toBe(true);
    expect(isEditableTarget(document.createElement("input"))).toBe(true);
    expect(isEditableTarget(heading)).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});
