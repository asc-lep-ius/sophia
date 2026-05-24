# Accessibility Baseline

This frontend pivot targets WCAG 2.2 AA for the SvelteKit surface under `/app`. The Phase 3 scaffold sets a small, enforceable baseline that future migrated pages must keep green.

## Automated Gate

- Playwright runs `frontend/tests/e2e/a11y.spec.ts` against `/app/study`, `/app/dashboard`, `/app/login`, and `/app/settings`.
- Axe uses the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, and `wcag22aa` tag set.
- The gate target is zero serious, critical, or structural axe violations. New route work should add that route to the same matrix before the NiceGUI migration reaches it.

## Manual and Design Requirements

- Focus visibility: every interactive element must expose a visible focus indicator with at least a 3:1 contrast change against adjacent colors.
- Focus not obscured: sticky headers, overlays, and focus mode controls must not cover the focused control. This includes the skipped-to main landmark.
- Target size: pointer targets should be at least 24 by 24 CSS pixels, with the default shell controls using 44 px or larger where space allows.
- Keyboard parity: every mouse action on the study surface needs a keyboard equivalent and visible focus order.
- Dragging alternatives: any future drag reorder, grouping, or scheduling control must provide buttons, menus, or keyboard shortcuts that perform the same action.
- Reduced motion: non-essential animation must respect `prefers-reduced-motion: reduce`.
- Theme contrast: `light`, `dark`, and `oled` themes must preserve WCAG AA contrast for text, borders that convey state, and focus rings.
- German overflow: `frontend/tests/e2e/de-overflow.spec.ts` fixes a 320 px viewport regression gate with long German chrome strings.

## Regression Practice

When a page adds new workflow controls, update the a11y matrix and include at least one test path that reaches the controls in their loaded state. Do not suppress axe rules without documenting the user impact, the reason the finding is false positive or deferred, and the replacement manual check.