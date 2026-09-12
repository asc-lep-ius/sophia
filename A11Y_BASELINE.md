# Accessibility Baseline

This frontend pivot targets WCAG 2.2 AA for the SvelteKit surface under `/app`. The Phase 4 scaffold keeps a small, enforceable baseline that future migrated pages must keep green.

## Automated Gate

- Playwright runs `frontend/tests/e2e/a11y.spec.ts` against `/app/study`, `/app/dashboard`, `/app/review`, the four `/app/quickstart` steps, `/app/content`, `/app/content/sources`, `/app/topics`, `/app/login`, and `/app/settings`.
- Axe uses the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, and `wcag22aa` tag set.
- The gate target is zero serious, critical, or structural axe violations. New route work should add that route to the same matrix before the NiceGUI migration reaches it.
- `frontend/tests/e2e/de-overflow.spec.ts` runs the same anchor routes at a 320 px German viewport and must stay green before merge.
- `frontend/tests/e2e/high-traffic-mobile.spec.ts` runs dashboard, quickstart, review, lectures, the content-source page and topics at 375 px and again at 320 px. Two widths, not one: a layout that fits the common phone and not the narrowest viewport the reflow criterion covers has not passed reflow.

## Manual and Design Requirements

- Focus visibility: every interactive element must expose a visible focus indicator with at least a 3:1 contrast change against adjacent colors.
- Focus not obscured: sticky headers, overlays, and focus mode controls must not cover the focused control. This includes the skipped-to main landmark.
- Target size: pointer targets should be at least 24 by 24 CSS pixels, with the default shell controls using 44 px or larger where space allows.
- Keyboard parity: every mouse action on the study surface needs a keyboard equivalent and visible focus order.
- Dragging alternatives: any future drag reorder, grouping, or scheduling control must provide buttons, menus, or keyboard shortcuts that perform the same action.
- Reduced motion: non-essential animation must respect `prefers-reduced-motion: reduce`.
- Theme contrast: `light`, `dark`, and `oled` themes must preserve WCAG AA contrast for text, borders that convey state, and focus rings.
- Theme persistence: `sophia-theme` is the SSR source of truth. Client controls may update `document.cookie`, `data-theme`, and `color-scheme` immediately, but must not move the source of truth to local storage.
- Font baseline: Inter remains the default chrome and content stack. Atkinson Hyperlegible is reserved as an accessibility opt-in through `data-font="hyperlegible"`, using local/system availability and the same sans-serif fallbacks; no external font network fetch is required for the baseline.
- Web-vitals status: `/api/metrics/web-vitals` is reserved only. The frontend may dynamically load `web-vitals` and make a no-body typed POST to the placeholder endpoint, but it must not send metric payloads, block rendering, or surface failures to users.
- German overflow: long German chrome strings must remain inside the 320 px viewport.
- Charts and figures: every figure ships a `<figcaption>`, a prose summary reached through `aria-describedby`, and a table carrying the same values. The drawn marks are `aria-hidden` because they repeat the table rather than adding to it — a screen reader that skips them misses nothing. See `docs/frontend-dashboard-charts.md`.
- Operational states: a dashboard panel says which of ready, empty, unauthorized and failed it is in. Rendering a refused scope or a dead service as an empty panel teaches the learner to distrust the panels that do have data.
- Filters and drawers: a list's filter state belongs in the URL, and so does whether a mobile filter drawer is open. Both are reached by submitting a GET form rather than by following a hand-built query string, so the panel works before hydration, survives a reload, and closes on the back gesture. A drawer that can only be opened by script is a filter set some learners cannot reach.
- Content language: a page showing course material names the content language and the interface language separately, and never merges them. Neither the UI locale nor `Accept-Language` may decide what language the material is in; an explicit `?lang=` travels with the learner across the content surfaces.
- Progressive enhancement: a write that a learner has to complete — the content upload is the current one — works as a plain form post. Client enhancement may add progress, cancellation or a retry, never the only working path. `frontend/tests/e2e/content-topics.spec.ts` runs that upload with JavaScript switched off.

## Regression Practice

When a page adds new workflow controls, update the a11y matrix and include at least one test path that reaches the controls in their loaded state. Do not suppress axe rules without documenting the user impact, the reason the finding is false positive or deferred, and the replacement manual check.