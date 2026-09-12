# Long-Tail Migration Scope

Status: accepted 2026-09-12

## Context

Issue #101 migrates search, Chronos, Chronos history, calibration and TISS
registration to SvelteKit. Its acceptance criteria are narrow and specific:
live search over debounced REST, replacement Playwright coverage for every
page, and Chronos dates, statuses and empty states matching the legacy service.

The NiceGUI pages behind those five routes carry considerably more than that.
`chronos.py` alone is 713 lines and holds six separate writes. Migrating every
one of them is not what the criteria ask for, and #101's own out-of-scope list
says "new Chronos features beyond current page parity" — so this note records
what was migrated, what was not, and why, rather than leaving #102 to discover
the difference by deleting the pages.

## Migrated

| Surface | What it does now |
|---|---|
| `/app/search` | Debounced REST search with `AbortController` and an out-of-order guard; the same query answered server-side for `?q=`; source and kind filters in the URL; the Bloom retrieval prompt |
| `/app/chronos` | Upcoming deadlines with the legacy relative phrasing and the UTC instant behind it, the workload summary, deadline sync, mark-complete |
| `/app/chronos/history` | Past deadlines with the legacy outcome classification, the outcome filter in the URL, the effort-calibration figure |
| `/app/calibration` | Predicted against measured, with retired-scorer rows declared and excluded, and the server's blind-spot verdict |
| `/app/register` | TISS favourites, connection states, a course's target, groups and exam dates, and a registration attempt |

## Deliberately not migrated

These stayed on the NiceGUI pages. Each is reachable through the API, so none
of them is blocked on backend work.

- **Effort estimation** (`POST /api/deadlines/estimates`). The legacy dialog is
  scaffold-aware — `open`, `minimal` and `full` produce three different forms —
  and the scaffold is chosen per deadline type. It is a feature, not a
  rendering of data the page already has.
- **Timers and manual time entries** (`/api/deadlines/{id}/timer/start`,
  `/timer/stop`, `/api/deadlines/time-entries`). A running timer is live state
  with a once-a-second display; the migrated page shows tracked hours from the
  workload endpoint but cannot start or add to them.
- **Post-deadline reflection** (`POST /api/deadlines/reflections`). The history
  surface reports whether a deadline was reflected on — that is what its
  outcome classification rests on — but offers no way to add one.
- **Calendar export** (`GET /api/deadlines/ics`).
- **Effort distribution chart**
  (`GET /api/deadline-history/effort-distribution`). The workload summary on
  `/app/chronos` covers the totals; the per-day stacked figure did not move.
- **The search Bloom lock-out.** The legacy page disabled every other result
  until the retrieval prompt was answered. The prompt moved; the lock did not.
  Trapping a learner behind a textarea they cannot skip is a dark pattern, and
  nothing in #101 asks for it.
- **The registration countdown's 60-second refresh.** The countdown is computed
  from the instant the server rendered with; it goes stale until a reload
  rather than ticking.

## Removed on purpose, not deferred

Three legacy calibration visualisations — the mastery heatmap, the per-topic
tier-progression charts, and the Socratic difficulty feedback — are not on the
migrated page and should not come back in this shape. They were computed in the
page from raw study sessions, and #101 is explicit that calibration "reads
server-computed figures only". The tier thresholds in particular existed in
three places at once: `calibration_service._score_to_tier`,
`calibration.get_current_tier`, and the API's own difficulty levels, with
different cut-offs in at least two of them. Re-deriving a learner's mastery
tier in a browser from a handful of sessions is the "false precision from
sparse data" the research adjustment on #101 names as an anti-pattern.

## What this means for #102

#102 retires NiceGUI. The seven items above are what a learner loses on the day
the pages are deleted, and each is a decision rather than an oversight. The
practical reading: effort estimation, time tracking and reflection together are
one coherent feature — Chronos' predict-act-reflect loop — and are worth
migrating as one piece rather than five dialogs. ICS export and the effort
distribution chart are independent and small. The Bloom lock-out and the
countdown refresh should stay gone.

## Guardrails

- `frontend/tests/fixtures/chronos-date-parity.json` is read by both
  `frontend/tests/unit/chronos-dates.test.ts` and
  `tests/unit/gui/test_chronos_parity.py`. The Python module is not marked for
  phase 5 removal: once the NiceGUI page is deleted, those cases are the only
  record of what the phrasing was.
- `tests/unit/gui/test_surface_routes.py` holds both halves of the
  arrangement — nothing in the legacy app navigates to its own copies, and the
  pages stay served so a `/legacy/` link resolves.
- `tests/unit/gui/test_phase5_retirement.py` requires every module marked for
  deletion to name a replacement file that exists.
