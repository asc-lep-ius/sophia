# Frontend Paraglide Decision

Status: accepted 2026-05-25

## Context

The frontend pivot plan originally described UI i18n as Paraglide JS via
`@inlang/paraglide-sveltekit`. That package is no longer the branch baseline:
npm marks `@inlang/paraglide-sveltekit@0.16.1` as deprecated and directs v2
users to use `@inlang/paraglide-js` directly.

The current `frontend-pivot-phase-0` branch already follows the v2 path:

- `frontend/package.json` pins `@inlang/paraglide-js` to `2.18.1`.
- `frontend/vite.config.ts` runs `paraglideVitePlugin(...)` with
  `strategy: ["cookie", "preferredLanguage", "baseLocale"]`.
- `frontend/src/hooks.server.ts` imports the generated
  `$lib/paraglide/server` middleware and composes it with the local context
  handle via SvelteKit `sequence(...)`.
- `frontend/src/lib/paraglide/` is generated output and is gitignored.

## Decision

Use generated Paraglide JS v2 middleware from `@inlang/paraglide-js`, not the
retired `@inlang/paraglide-sveltekit` adapter package.

The supported runtime shape is:

1. Generate `frontend/src/lib/paraglide/` with
   `pnpm -C frontend run paraglide:compile`.
2. Wire SvelteKit through the generated `paraglideMiddleware(...)` in
   `frontend/src/hooks.server.ts`.
3. Keep URL space org-, course-, and locale-agnostic under `/app`; do not add a
   `/[lang]` route prefix.
4. Negotiate UI locale through the Paraglide cookie, browser preference, then
   base locale `en`. The `sophia-locale` cookie remains a compatibility alias
   for existing local context setup.

## Guardrails

- `frontend/scripts/assert-package-contract.mjs` requires
  `@inlang/paraglide-js@2.18.1` and rejects `@inlang/paraglide-sveltekit` in
  `package.json` or `pnpm-lock.yaml`.
- `pnpm -C frontend run paraglide:check` regenerates Paraglide output and
  validates message keys.
- `frontend/tests/unit/paraglide-decision.test.ts` verifies the decision record,
  Vite plugin, generated middleware hook, and package contract stay aligned.
- CI runs the package guards and Paraglide check through
  `frontend-contract-guards` and `frontend-paraglide`.

## Related Frontend Tests

- `frontend/tests/unit/smoke.test.ts` covers the scaffold shell and study
  controls that consume generated Paraglide messages.
- `frontend/tests/unit/locale.test.ts` covers locale normalization and fallback
  behavior used by the SvelteKit locals setup.
- `frontend/tests/unit/web-vitals.test.ts` covers the reserved web-vitals helper
  and typed `/api/metrics/web-vitals` endpoint call.
- `frontend/tests/e2e/de-overflow.spec.ts` keeps German UI strings from
  overflowing the `/app` chrome.
