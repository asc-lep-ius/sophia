# Accessibility Baseline

This frontend pivot targets WCAG 2.2 AA for the SvelteKit surface under `/app`. The Phase 4 scaffold keeps a small, enforceable baseline that future migrated pages must keep green.

## Automated Gate

- Playwright runs `frontend/tests/e2e/a11y.spec.ts` against `/app/study`, `/app/dashboard`, `/app/login`, and `/app/settings`.
- Axe uses the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, and `wcag22aa` tag set.
- The gate target is zero serious, critical, or structural axe violations. New route work should add that route to the same matrix before the NiceGUI migration reaches it.
- `frontend/tests/e2e/de-overflow.spec.ts` runs the same anchor routes at a 320 px German viewport and must stay green before merge.

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

## Regression Practice

When a page adds new workflow controls, update the a11y matrix and include at least one test path that reaches the controls in their loaded state. Do not suppress axe rules without documenting the user impact, the reason the finding is false positive or deferred, and the replacement manual check.