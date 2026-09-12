import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { THEMES } from "../../src/lib/theme";

/**
 * Contrast the axe gate cannot see.
 *
 * `frontend-a11y` runs against the e2e fixture, which always reports
 * `theme: "light"`. Every accent-coloured control therefore passes axe on the
 * one theme where the accent happens to be dark, while the other two ship a
 * WCAG 1.4.3 failure nobody is told about. This checks all three.
 */

const APP_CSS = readFileSync(join(process.cwd(), "src/app.css"), "utf8");

const WCAG_AA_NORMAL_TEXT = 4.5;

function themeBlock(theme: string): string {
  const selector =
    theme === "light" ? ":root {" : `:root[data-theme="${theme}"] {`;
  const start = APP_CSS.indexOf(selector);
  expect(start, `${theme} theme block`).toBeGreaterThan(-1);
  return APP_CSS.slice(start, APP_CSS.indexOf("}", start));
}

function token(block: string, name: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  expect(match, `--${name}`).not.toBeNull();
  return match?.[1] ?? "";
}

function relativeLuminance(color: string): number {
  const channels = [1, 3, 5].map((offset) => {
    const value = Number.parseInt(color.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return (
    0.2126 * (channels[0] ?? 0) +
    0.7152 * (channels[1] ?? 0) +
    0.0722 * (channels[2] ?? 0)
  );
}

function contrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function svelteSources(directory: string): [string, string][] {
  const files: [string, string][] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...svelteSources(path));
    } else if (entry.name.endsWith(".svelte")) {
      files.push([path, readFileSync(path, "utf8")]);
    }
  }
  return files;
}

describe("accent contrast across every theme", () => {
  it.each(THEMES)("%s keeps --on-accent readable on --accent", (theme) => {
    const block = themeBlock(theme);

    expect(
      contrastRatio(token(block, "on-accent"), token(block, "accent")),
    ).toBeGreaterThanOrEqual(WCAG_AA_NORMAL_TEXT);
  });

  it("never hardcodes a colour literal in a component", () => {
    // Every colour belongs to a theme. The accent in particular is dark in
    // light mode and light in the other two, so a fixed value is wrong for at
    // least one of them — white read 1.9:1 on dark before this landed.
    const offenders = svelteSources(join(process.cwd(), "src"))
      .filter(([, content]) => /color:\s*#[0-9a-fA-F]{3,8}\s*;/.test(content))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
