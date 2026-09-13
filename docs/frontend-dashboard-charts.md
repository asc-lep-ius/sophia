# Dashboard Charts Decision

Status: accepted 2026-09-12

## Context

Issue #99 migrates the dashboard to SvelteKit and asks for "the expected
dashboard content and charts". It also requires, before any of it is built, a
note that names the chart package pinned on implementation day — or explains
why there is not one — and that weighs bundle size, accessibility support, SSR
compatibility, theming, and the ability to render deterministic test output.

Two constraints already in the repository decide most of this.

The **bundle budget** is a merge gate. `frontend/package.json` caps the built
client at 95 KB gzipped and the study surface already spends roughly 65 KB of
it, with the comment there noting the remaining headroom is "room for roughly
one more surface". This issue adds three surfaces.

The **accessibility requirement** is not a chart feature. `A11Y_BASELINE.md`
and the research adjustment on #99 both require that every figure have a text
or tabular equivalent carrying the same numbers, reachable by keyboard and
readable by a screen reader. That equivalent is the primary artefact; a drawn
figure is a second rendering of numbers the page must already contain in
markup.

## Decision

**No chart dependency is added. Dashboard figures are hand-written inline SVG
and CSS over data the page already renders as a table.**

There is therefore no package to pin. The version the note was asked to record
is: none.

What this means concretely:

1. Every figure is a `<figure>` with a `<figcaption>` naming it, an
   `aria-describedby` pointing at a prose summary, and a `<table>` carrying the
   same rows. The table is real markup, not a toggle-behind-a-button.
2. The drawn part is `aria-hidden`. It repeats the table; it never adds a value
   the table lacks. A screen reader reads the caption, the summary and the
   table, and misses nothing.
3. Marks are `<rect>`s and `<line>`s positioned from server-computed numbers.
   No layout maths runs in an animation frame, so a server render and a browser
   render produce byte-identical output.
4. Colour comes from the same CSS custom properties the rest of the shell uses
   (`--accent`, `--muted`, `--danger`), so the three themes theme the figures
   for free and no palette is duplicated in JavaScript.
5. State is never carried by colour alone: every band also carries a label.

## Why not a library

Measured against the five criteria the issue named:

| Criterion | Library | Inline SVG |
|---|---|---|
| Bundle size | 20–120 KB gzipped for the general-purpose ones; the smallest Svelte-native options still pull a scale/shape layer | ~0; it is markup in a component that already ships |
| Accessibility | Ranges from "renders to canvas, invisible to a screen reader" to "SVG with a title"; none removes the obligation to ship the table | The table *is* the implementation |
| SSR | Canvas-based options cannot render on the server at all; SVG-based ones usually can, with care about measurement | Renders on the server by construction — the shapes are computed from numbers, not from measured DOM |
| Theming | A second palette, expressed in JS, that has to be kept in step with the CSS custom properties | The CSS custom properties, directly |
| Deterministic test output | Animation, responsive resize observers and device-pixel rounding all make snapshots flaky | A pure function of the data; a unit test asserts the bar geometry |

The shapes this dashboard needs — a due-pressure bar row, a calibration
predicted-versus-actual comparison — are a handful of rectangles. A library
earns its bundle cost on axes, scales, legends, brushing and zoom. None of
those appear here.

## When to revisit

Reopen this decision when a dashboard figure needs any of: a continuous time
axis with tick negotiation, interactive brushing or zoom, more than roughly
fifty marks per figure, or a projection. At that point pin a package, add its
gzipped cost to the size-limit budget in the same commit, and keep rules 1 and 2
above — the table equivalent is not negotiable regardless of what draws the
figure.

## Guardrails

- `frontend/tests/unit/dashboard-figures.test.ts` asserts the bar geometry is a
  pure function of its input and that a figure never ships without its table.
- `frontend/tests/e2e/a11y.spec.ts` covers `/app/dashboard` with axe.
- `pnpm -C frontend run size-limit` is the budget gate; it is why this note
  exists.
