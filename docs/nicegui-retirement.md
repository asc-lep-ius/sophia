# NiceGUI Retirement

Status: accepted 2026-09-12 — issue #102, phase 5 of the frontend pivot

This is the deletion checklist the issue asked for, written so that a bug
report six months from now can find out what was removed, what replaced it,
and what was dropped deliberately. Read it alongside
[frontend-long-tail-migration.md](frontend-long-tail-migration.md), which
records what phases 4a–4c chose not to migrate.

## What was removed

| Item | Replacement |
|---|---|
| `src/sophia/gui/` (10,048 lines across 54 files) | `src/sophia/api/` + `frontend/` |
| `sophia gui launch` (`src/sophia/cli/gui.py`) | `docker compose up`, then `/app/` |
| `src/sophia/gui/auth_bridge.py` | None needed — the SvelteKit app is a first-class client of `sophia.api.sessions` |
| `Dockerfile.gui`, `Dockerfile.gui.cuda`, `Dockerfile.nicegui`, `ci/Dockerfile.cuda-base` | `Dockerfile` (api), `Dockerfile.frontend` |
| `sophia-gui`, `sophia-gui-gpu` Compose services | `api` + `frontend` |
| `model-cache` volume | None — no service mounts a Hugging Face cache any more |
| `/legacy/*` and the bare-root proxy fallback | `/app/*`; `/` is a `308` to `/app/`, everything else is `404` |
| `docker-nicegui-build`, `docker-gui-build-gpu` CI jobs | `docker-api-build`, `docker-frontend-build`, `docker-proxy-build` |
| `nicegui` dependency and the `web` extra | — |
| `playwright`, `pytest-playwright`, `axe-playwright-python` dev deps | `frontend`'s own `@playwright/test` and `axe-core` |
| `SOPHIA_GUI_HOST`, `SOPHIA_GUI_PORT`, `SOPHIA_GUI_RELOAD`, `SOPHIA_AUTO_SYNC`, `session_keepalive_interval` | — |

`ci/Dockerfile.cuda-base` went too, after a first pass kept it. It carried the
CUDA runtime, ffmpeg and the Whisper stack, which read like a non-GUI artefact
worth saving — but it is a *base* image, not a runnable one. Its runtime stage
never copies `src/`, and `uv sync` installs this project editable, so the
`.pth` file in the image points at an `/app/src` that does not exist there; the
venv's interpreter symlink also dangles across the stage boundary. The thing
that repaired both was `Dockerfile.gui.cuda`, which copied the source and
re-synced on top — and that is a NiceGUI image. Keeping the base alone would
have preserved a layer nothing builds and nothing can run.

## Test classification

Every deleted test module falls into one of three classes, which is the
classification the research adjustment on #102 asked for.

**Migrated to a service test.** The behaviour was domain logic that outlives
the page.

| Deleted | Now at |
|---|---|
| `tests/unit/gui/test_overview_service.py` | `tests/unit/test_course_overview.py`, against `src/sophia/services/course_overview.py` |
| `tests/unit/gui/test_chronos_parity.py` | `tests/unit/test_chronos_parity.py`, carrying the legacy phrasing rule itself |

**Superseded — the same behaviour is asserted elsewhere.** These were already
duplicates on the day they were deleted: the GUI service wrapped a
`sophia.services.*` function, or re-implemented one, and the API or the
SvelteKit suite covers the same ground.

| Deleted | Covered by |
|---|---|
| `test_dashboard.py`, `test_quickstart.py`, `test_review.py`, `test_review_card.py` | `frontend/tests/unit/dashboard-page.test.ts`, `quickstart-route.test.ts`, `review-page.test.ts` |
| `test_lectures.py`, `test_topics.py` | `frontend/tests/unit/{content,topics}-page.test.ts` |
| `test_search.py`, `test_chronos.py`, `test_calibration.py`, `test_register.py` | `frontend/tests/unit/{search,chronos,calibration,register}-page.test.ts` |
| `test_chronos_service.py` | `tests/api/test_deadlines.py`, `tests/api/test_deadline_history.py`, `tests/unit/test_chronos.py`. Its `compute_effort_distribution` was a copy of `services/chronos_history.compute_effort_distribution` |
| `test_study_service.py` (in part) | `tests/unit/test_athena_session.py`, `tests/api/test_study.py`. Its interleave selection was a copy of `athena_session._select_interleave_topics`. **Not** fully superseded: its three `check_novel_topic` cases have no replacement — see "capabilities dropped" |
| `test_review_service.py` | `tests/unit/test_fsrs_review.py`, `tests/api/test_review.py`. Its `RATING_SCORES` was a third copy of `athena_review.SELF_RATING_SCORES` |
| `test_calibration_service.py` | `tests/api/test_calibration.py`, `tests/unit/test_athena_confidence.py` |
| `test_quickstart_service.py`, `test_topic_service.py`, `test_search_service.py` | `tests/api/test_quickstart.py`, `tests/api/test_topics.py`, `tests/api/test_search.py` |
| `test_hermes_service.py`, `test_discover_lectures.py` | `tests/unit/test_hermes_catalog.py`, `tests/api/test_content_sources.py`; the status filters moved to `frontend/src/lib/content/filters.ts` |
| `test_pipeline_service.py` | `tests/unit/test_hermes_pipeline.py`, `tests/unit/test_job_runner.py` |
| `test_lectures_setup.py` | `tests/unit/test_hermes_setup.py`; the wizard's own entry point is `sophia lectures setup` |
| `test_health.py` | `tests/api/test_health.py`, `tests/api/test_ready.py` |
| `test_settings.py`, `test_settings_jobs.py` | `tests/api/test_settings.py`, `frontend/tests/unit/settings-page.test.ts` |
| `tests/api/test_nicegui_auth_bridge.py` | `tests/api/test_sessions.py`, `tests/api/test_auth.py` |
| `tests/integration/gui/*` | `frontend/tests/e2e/{a11y,de-overflow,high-traffic-mobile,long-tail,content-topics,shell,study-mobile}.spec.ts` |
| `tests/api/test_import_boundaries.py` | `tests/api/test_nicegui_retirement.py`, which applies the rule to all of `src` rather than to the API package alone |

**GUI-only — deleted with rationale.** These asserted things about the NiceGUI
runtime. There is nothing for them to assert once it is gone.

| Deleted | Why nothing replaces it |
|---|---|
| `test_app.py` | The NiceGUI app factory and its DI lifecycle |
| `test_layout.py`, `test_components.py`, `test_error_display.py`, `test_course_selector.py`, `test_course_overview.py` | Rendering helpers for NiceGUI widgets. `AppShell.svelte` and its own specs are the shell now |
| `test_accessibility.py` | Keyboard-shortcut and chart-table helpers for NiceGUI. The a11y gate is `frontend/tests/e2e/a11y.spec.ts` against axe, which is stricter |
| `test_storage_map.py`, `test_session_store.py`, `test_course_state.py` | `app.storage` key bookkeeping. Study-session state is server-side, at `/api/study/sessions` |
| `test_job_registry.py` | Per-user job bookkeeping in browser storage, for background work only the GUI started |
| `test_session_health.py` | The keepalive monitor the NiceGUI process ran. Nothing else polled it, and the setting is gone |
| `test_error_service.py` | `classify_error` mapped exceptions to a toast category. The API answers with the error envelope in `sophia/api/errors.py` |
| `test_math_input.py` | LaTeX input with a KaTeX preview, and the HTML sanitisation `ui.html()` required. Svelte escapes by default; see "capabilities dropped" below |
| `test_surface_routes.py` | Asserted that nothing in the legacy app linked to its own pages and that the pages stayed served. Both halves are moot |
| `test_phase5_retirement.py` | The marking that authorised this deletion. `tests/api/test_nicegui_retirement.py` replaces it |
| `tests/unit/test_marker_scope.py` | Guarded the session-wide `e2e` marker in `tests/integration/gui/conftest.py`. No Python test is marked `e2e` any more |

## Capabilities dropped

The seven items in
[frontend-long-tail-migration.md](frontend-long-tail-migration.md) are what a
learner loses on the deadline surfaces. Four more go with the rest of the tree:

- **LaTeX flashcard authoring.** `math_input`, `latex_assist` and the assist
  ladder that widened or narrowed the symbol palette by how many LaTeX cards a
  learner had written. The migrated review surface has no LaTeX affordance at
  all. Re-adding it is a frontend feature, which #102 puts out of scope; the
  thresholds are in git history at `22e7b71` if it comes back.
- **Background-job progress in the browser.** The settings page listed running
  and finished jobs from browser storage. The jobs it tracked were started by
  the GUI, so with the GUI gone there is nothing to list; `sophia jobs list`
  covers scheduled work.
- **Declaring a topic novel before a pre-test.** `study_service.check_novel_topic`
  plus the "I haven't encountered this yet" button on the legacy study page.
  A topic with no prior session and no confidence rating above the baseline was
  offered to the learner as one they could declare new, which forced the whole
  pre-test down to `DifficultyLevel.CUED` rather than asking transfer questions
  about material never seen. This is the one dropped item that is genuinely
  learning-design behaviour rather than an affordance, and it has no counterpart
  in the API or on `/app/study`. The rule is in git history at `22e7b71`
  (`src/sophia/gui/services/study_service.py`), and bringing it back means an
  API endpoint plus a control on the predict step — which is why it is recorded
  here rather than reimplemented under a retirement issue.
- **GPU transcription from a container.** See the note on
  `ci/Dockerfile.cuda-base` above: what actually ran it was a NiceGUI image.
  `sophia lectures transcribe` on a CUDA host with `uv sync --extra hermes` is
  unaffected.

The course-health heuristics were *not* dropped — they are the piece of this
tree that most clearly belonged in the service layer, and they moved to
`src/sophia/services/course_overview.py` before the delete. It has no caller
yet, which its docstring says plainly.

## Before merging: the traffic audit

The issue's Definition of Ready requires one full release cycle at zero
`/legacy/*` traffic, and that evidence has to be attached to the merge request
rather than inferred from the code. It is the one item on this checklist that
cannot be satisfied from a checkout. The proxy logs JSON to stdout, so on the
deployment host:

```bash
docker compose -f docker-compose.prod.yml logs --since 720h --no-log-prefix proxy \
  | jq -r 'select(.request.uri | startswith("/legacy")) | "\(.ts) \(.request.uri) \(.status)"' \
  | tee /tmp/legacy-traffic-audit.txt
wc -l < /tmp/legacy-traffic-audit.txt   # expected: 0
```

A non-empty result is not automatically a blocker — health probes and crawlers
show up here too — but it has to be read before merging, not after.

## Rollback

Roll back to the last pre-removal release tag. Do not re-add a `/legacy/*`
route to a newer image: nothing in the current test suite covers that path, so
a half-retained legacy route would be exactly the unaudited surface this phase
removed. `22e7b71` is the last commit on which the tree still existed, so
`${LOCAL_REGISTRY}/nicegui:<the last master SHA before this branch merges>` is
the last image tag the pipeline pushed.

## Measured deltas

| Measure | Before | After |
|---|---|---|
| Packages in `uv.lock` | 232 | 215 |
| Python source under `src/sophia` | 10,048 lines of `gui/` | 0 |
| Production Compose services | 7 | 6 |
| Container ports exposed to the app network | `3000`, `8000`, `8080` | `3000`, `8000` |
| Images built and pushed per pipeline | 4 | 3 |
| NiceGUI production image | 1.21 GB on disk / 316 MB compressed | not built |
| API production image | 477 MB | 478 MB |

Both images were built locally from `Dockerfile.nicegui` and `Dockerfile` at
the pre-removal commit and again at HEAD, on a daemon using the containerd
snapshotter — which is why the retired image has two numbers. `docker image ls`
reports the uncompressed on-disk size and `docker image inspect .Size` reports
the compressed size a registry pull moves. The retirement removes the whole
image, so the saving is the whole of either figure, per deploy host and per
pipeline run.

The API image is unchanged within measurement noise, which is the expected
result: it never installed the `web` extra, so dropping the dependency could
not shrink it. The frontend and proxy images are untouched. The CI image loses
its Playwright chromium layer, which the Python suite no longer needs.
