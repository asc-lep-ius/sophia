# Sophia (Σοφία)

*"I am the love of wisdom, the spirit that kindles the flame of truth in those who seek it."*

A student toolkit for TU Wien. It takes over the tedious parts of academic
life: getting a spot in the group you want, turning lecture recordings into
something you can search and study from, keeping track of deadlines and how
long things actually take. What it does not take over is the thinking. Every
feature is built so that the prediction, the retrieval and the reflection stay
yours.

**Status:** early development. Kairos (TISS registration with a scheduler),
Hermes (lecture knowledge base), Athena (study sessions, spaced review,
calibration), Chronos (deadline coach) and the web interface at `/app/` work.
Bücherwurm discovers textbook references; its download and library features
are not built. The project is proprietary; see [LICENSE](LICENSE).

| Section | What it covers |
|---|---|
| [Schnellstart (Deutsch)](#schnellstart-deutsch) | Einrichten, LV-Anmeldung planen, Vorlesung zu Anki-Deck |
| [Getting started (English)](#getting-started-english) | Set up, schedule a registration, lecture to Anki deck |
| [What Sophia does](#what-sophia-does) | The modules, the web interface, the CLI |
| [How studying works](#how-studying-works) | Sessions, review, calibration, deadlines |
| [Philosophy](#philosophy) | Why Sophia asks instead of telling, and the evidence it rests on |
| [Architecture and stack](#architecture-and-stack) | Ports and adapters, API, worker, frontend |
| [Setup details](#setup-details) | Extras, LLM providers, system tools, privacy |
| [Development](#development) | Gates, tests, Docker, CI |
| [Roadmap](#roadmap) | What is next |
| [Quick reference](#quick-reference) | Commands at a glance |

---

## Schnellstart (Deutsch)

### Voraussetzungen

Du brauchst ein Terminal, Python 3.12 oder neuer, Git und den Paketmanager
`uv`.

- **Terminal öffnen.** Windows: `Win + R`, `wt`, Enter. macOS: `Cmd + Space`,
  „Terminal“. Linux: `Strg + Alt + T`.
- **Python prüfen:** `python3 --version`. Zeigt es 3.12 oder höher, weiter.
  Sonst von [python.org](https://www.python.org/downloads/) installieren
  (Windows: Häkchen bei „Add Python to PATH“).
- **uv installieren.** macOS/Linux:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`. Windows (PowerShell):
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
  Danach Terminal schließen und neu öffnen.
- **Sophia installieren und einloggen:**

```bash
git clone https://gitlab.com/mipkovich/sophia.git && cd sophia
uv sync
uv run sophia auth login
```

Du wirst nach deinen TU-Wien-Zugangsdaten gefragt, dieselben wie für TUWEL und
TISS. MFA ist Pflicht; mit `--save-credentials` speichert Sophia Passwort und
TOTP-Geheimnis im Schlüsselbund deines Betriebssystems und erneuert eine
abgelaufene Sitzung selbst. Die Zugangsdaten gehen nur an TU Wiens eigene
Server.

| Problem | Lösung |
|---|---|
| `command not found` nach der uv-Installation | Terminal schließen und neu öffnen. |
| Login schlägt fehl | Zugangsdaten prüfen; Details mit `uv run sophia --debug auth login`. |
| `git` nicht gefunden | [git-scm.com](https://git-scm.com/downloads) installieren, Terminal neu starten. |

### Kairos: LV-Anmeldung planen

Statt um Mitternacht F5 zu hämmern, installierst du einen System-Timer. Sophia
meldet dich an, sobald das Fenster aufgeht.

```bash
uv run sophia register groups 186.813
uv run sophia register go 186.813 --preferences "1,3" --schedule
```

`186.813` ist deine LVA-Nummer. Der erste Befehl zeigt alle Gruppen mit
Wochentag, Zeit, Raum und Belegung. `--preferences "1,3"` ist deine
Wunschreihenfolge (Indizes aus der Tabelle); ist Gruppe 1 voll, versucht Sophia
Gruppe 3. `--schedule` installiert einen Timer (systemd, launchd oder
Aufgabenplanung), ein offenes Terminal ist nicht nötig. `sophia jobs list` zeigt
geplante Jobs, `sophia jobs cancel <job-id>` storniert einen. Ohne
`--schedule` wartet `--watch` stattdessen im Vordergrund.

### Hermes + Athena: von der Vorlesung zum Anki-Deck

```bash
uv sync --extra hermes --extra llm --extra athena
uv run sophia lectures setup            # GPU erkennen, Whisper-Modell, LLM-Anbieter; einmalig
uv run sophia lectures list             # Opencast-Aufzeichnungen deiner Kurse, mit Modul-ID
uv run sophia lectures process <modul-id>
```

`process` nimmt die Untertitel des TUWEL-Players, wo es welche gibt, lädt sonst
die Aufzeichnung und transkribiert sie mit Whisper, indiziert alles für die
semantische Suche und extrahiert Themen. Auf einer CUDA-GPU dauert eine
Vorlesung Minuten, auf der CPU deutlich länger. `--materials` indiziert
zusätzlich die Kurs-PDFs.

Danach läuft das Lernen im Browser (siehe unten) oder im Terminal:

```bash
uv run sophia study confidence <modul-id>   # Selbsteinschätzung je Thema, vor dem Lernen
uv run sophia study session <modul-id>      # Pre-Test → Vorlesungsausschnitte → Post-Test → Karten
uv run sophia study export <modul-id>       # sophia-<modul-id>.apkg für Anki
```

Einen LLM-Anbieter brauchst du für die Themenextraktion und die Fragen:
Gemini oder Groq (kostenloses Kontingent, API-Key in `.env`), GitHub Models
(`GITHUB_TOKEN`) oder Ollama (lokal, kein Key). Der Setup-Wizard fragt danach.
Transkripte gehen an den gewählten Anbieter; mit Ollama bleiben sie lokal.

| Problem | Lösung |
|---|---|
| Der erste `lectures process` dauert lange | Normal: Whisper und das Embedding-Modell werden einmalig von Hugging Face geladen, mehrere Gigabyte. |
| GPU nicht erkannt | `nvidia-smi` prüfen; unter WSL braucht es WSL2 mit GPU-Passthrough. Ohne GPU läuft alles auf der CPU. |
| Keine Themen | `sophia lectures status <modul-id>` zeigt, welche Stufe fehlt. |
| Anki-Export schlägt fehl | `uv sync --extra hermes --extra llm --extra athena` nachholen; `uv sync` ohne Extras entfernt sie wieder. |

---

## Getting started (English)

### Prerequisites

A terminal, Python 3.12 or newer, Git and the `uv` package manager.

- **Open a terminal.** Windows: `Win + R`, `wt`, Enter. macOS: `Cmd + Space`,
  "Terminal". Linux: `Ctrl + Alt + T`.
- **Check Python:** `python3 --version`. 3.12 or higher is fine; otherwise
  install from [python.org](https://www.python.org/downloads/) (Windows: tick
  "Add Python to PATH").
- **Install uv.** macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
  Windows (PowerShell):
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
  Close and reopen the terminal afterwards.
- **Install Sophia and log in:**

```bash
git clone https://gitlab.com/mipkovich/sophia.git && cd sophia
uv sync
uv run sophia auth login
```

You are asked for your TU Wien credentials, the same ones TUWEL and TISS use.
MFA is mandatory; with `--save-credentials` Sophia keeps the password and the
TOTP secret in your OS keyring and renews a dead session on its own. The
credentials go to TU Wien's own servers and nowhere else.

| Problem | Solution |
|---|---|
| `command not found` after installing uv | Close the terminal and open a new one. |
| Login fails | Check the credentials; details with `uv run sophia --debug auth login`. |
| `git` not found | Install from [git-scm.com](https://git-scm.com/downloads) and restart the terminal. |

### Kairos: schedule a registration

Instead of refreshing TISS at midnight, install a system timer. Sophia submits
the instant the window opens.

```bash
uv run sophia register groups 186.813
uv run sophia register go 186.813 --preferences "1,3" --schedule
```

`186.813` is the course number. The first command lists every group with day,
time, room and enrolment. `--preferences "1,3"` is your order of preference
(indices from the table); if group 1 is full Sophia tries group 3. `--schedule`
installs a timer (systemd, launchd or Task Scheduler), so no terminal has to
stay open. `sophia jobs list` shows scheduled jobs, `sophia jobs cancel <job-id>`
removes one. Without `--schedule`, `--watch` waits in the foreground instead.

### Hermes + Athena: from a lecture to an Anki deck

```bash
uv sync --extra hermes --extra llm --extra athena
uv run sophia lectures setup            # detect GPU, pick a Whisper model and an LLM provider; once
uv run sophia lectures list             # Opencast recordings of your courses, with module ids
uv run sophia lectures process <module-id>
```

`process` takes the TUWEL player's captions where a lecture has them, otherwise
downloads the recording and transcribes it with Whisper, indexes everything for
semantic search and extracts topics. On a CUDA GPU a lecture takes minutes, on
the CPU much longer. `--materials` also indexes the course's PDFs.

From there, study in the browser (below) or in the terminal:

```bash
uv run sophia study confidence <module-id>  # rate each topic before studying it
uv run sophia study session <module-id>     # pre-test → lecture excerpts → post-test → cards
uv run sophia study export <module-id>      # sophia-<module-id>.apkg for Anki
```

An LLM provider is needed for topic extraction and question generation: Gemini
or Groq (free tiers, API key in `.env`), GitHub Models (`GITHUB_TOKEN`) or
Ollama (local, no key). The setup wizard asks for one. Transcripts go to the
provider you chose; with Ollama they stay on your machine.

| Problem | Solution |
|---|---|
| The first `lectures process` is slow | Normal: Whisper and the embedding model download once from Hugging Face, several gigabytes. |
| GPU not detected | Check `nvidia-smi`; WSL needs WSL2 with GPU passthrough. Without a GPU everything runs on the CPU. |
| No topics | `sophia lectures status <module-id>` shows which stage is missing. |
| Anki export fails | Run `uv sync --extra hermes --extra llm --extra athena`; a bare `uv sync` removes the extras again. |

---

## What Sophia does

| Module | Command | What it does |
|---|---|---|
| **Kairos** ⚡ | `sophia register` | TISS course and group registration with a preference list, watch mode and a system timer |
| **Hermes** 🎙️ | `sophia lectures` | Lecture knowledge base: captions or Whisper transcripts, semantic search, course PDFs, missed-lecture tracking |
| **Athena** 🎓 | `sophia study` | Topic extraction, confidence prediction, guided sessions, spaced review, self-explanation, Anki export |
| **Chronos** ⏰ | `sophia deadlines` | Deadline discovery from TUWEL, effort estimation, time tracking, reflection, per-course calibration, ICS export |
| **Plan** 🗺️ | `sophia plan` | One prioritised list across Chronos and Athena: deadlines, due reviews, confidence gaps, missed-lecture topics |
| **Bücherwurm** 📚 | `sophia books` | Textbook references from enrolled courses, with ISBN and metadata |
| **Status** 📊 | `sophia status` | Lectures, topics, cards and due reviews across all courses |
| **Quickstart** 🚀 | `sophia quickstart` | process → topics → confidence → session → export in one go, skipping finished steps |
| **Worker** ⚙️ | `sophia worker` | The processing worker behind the browser's "Process": claims a course's lectures and runs the Hermes stages |

### The web interface

`docker compose up -d proxy frontend api redis postgres` starts Caddy, the
SvelteKit frontend, the FastAPI backend, Postgres and Redis; the interface is
at `http://localhost/app/`. The API cannot start without a stored TU Wien
session, so run `sophia auth login --save-credentials` first. The processing
worker is a separate service that needs the NVIDIA container runtime:
`make docker-build-worker && docker compose up -d worker`.
[DEPLOYMENT.md](DEPLOYMENT.md) covers a real deployment.

| Route | What you do there |
|---|---|
| `/app/dashboard` | Due reviews, the week ahead, calibration, recent sessions |
| `/app/study` | Pick a course and a topic, then predict → work → reflect |
| `/app/review` | Everything due today, across all your courses |
| `/app/topics` | A course's topics, where each came from, and your prediction for it |
| `/app/content` | Lectures and uploads; scan for new recordings and start processing |
| `/app/search` | Semantic search over a course's lectures, with lecture and timestamp |
| `/app/chronos` | Deadlines and their history |
| `/app/register` | TISS favourites, a course's groups and the registration countdown; register from the browser |
| `/app/calibration` | Predicted against measured, per topic, never averaged |
| `/app/quickstart` | First run: name the topics you expect a course to cover and rate each before you have seen its lectures |
| `/app/settings` | Language and theme |

Flashcards, interleaved sessions, self-explanation and the Chronos
estimate → timer → reflection loop are in the CLI today and on their way to the
browser (see [Roadmap](#roadmap)).

---

## How studying works

### A session

A session is one topic, three steps.

1. **Predict.** You rate how well you know the topic, then answer one question
   from memory. The question is generated from the course's own lecture
   passages, and you cannot skip it: a guess, even a wrong one, is what makes
   the later comparison worth something.
2. **Work.** The rest of the deck. For each card you write a real answer (there is a
   minimum length), stay with the prompt for a few seconds, reveal the
   lecture passages the question came from, and grade yourself Again, Hard,
   Good or Easy. There is no answer key: the material is the reference.
3. **Reflect.** The first question again, from memory. Then a written
   reflection and a short pause before the numbers open: what you predicted,
   what you scored, and whether the two agree.

The floors (answer length, dwell time, the pause) are served by the API and
enforced by it, so a client that skips them cannot finish a session.

Questions come in three bands keyed to your own rating of the topic: cued
questions when you say you know little, explanation questions in the middle,
transfer questions when you say you know it well. All three ask for a written
answer.

### Review

Finishing a session schedules the topic's first review for the next day.
`/app/review` lists what is due across every course, asks you to write what
you remember before anything is revealed, and reschedules from your grade:
Again and Hard shrink the interval, Good and Easy stretch it, through a
difficulty-and-stability model (FSRS proper is on the roadmap). When an exam is
near, reviews that would fall after it are pulled forward.

### Calibration

Every prediction is kept with the score it was followed by, per topic and per
course, never blended into one number: being well calibrated for programming
says little about proofs. The calibration page shows the pairs; the study
picker offers the topic where your prediction most overshot your score first.

### Deadlines

Chronos runs the same loop on time instead of knowledge: discover deadlines
from TUWEL, estimate the effort, track the time, mark done, reflect on the
gap. Estimation prompts fade from a step-by-step breakdown to a bare number as
you log estimates and as your estimation error drops. `sophia deadlines calibration` shows the
error per course, and `sophia plan` merges deadlines, due reviews, confidence
gaps and missed-lecture topics into one ordered list.

### In the terminal

The CLI has a few things the browser does not yet: `study session --interleave`
mixes two or three topics, blind spots first, then topics from lectures you
marked missed; `study review` and `study export` handle flashcards; `study explain`
asks for a self-explanation of a wrong answer with prompts that fade as you
write more of them; `lectures mark-missed` and `lectures catch-up` track the
lectures you were not at.

---

## Philosophy

It would be easy to build a tool that decides what a course is about, writes
the cards and grades the answers. That feels productive. Sophia does not,
because the research on how learning happens points the other way.

**Maieutics.** Sophia is named for wisdom; her method is Socratic. In the
*Theaetetus*, Socrates calls himself a midwife: he cannot deliver the truth
for the student, only help the student deliver it. Sophia provides the
material, the questions and the timing. The construction stays yours.

**Predict, act, reflect.** Athena and Chronos ask you to commit to a
prediction before you act (how well do you know this topic, how long will this
take), then show you what happened next to it. The comparison is not the
lesson; what you make of it is. A study session asks for a written reflection
before the numbers open, Chronos asks you to explain the gap once it is shown,
and every pair is kept so a pattern can show over a semester. There are no
points, streaks or leaderboards. The reward is watching the gap narrow.

**Desirable difficulty.** Retrieving from memory before looking, spacing
reviews out, answering before being told: all of these slow you down now and
pay off later. Sophia never optimises for how easy a session feels.

**What Sophia will not do.** It orders what is due and points at the topics
where your prediction overshot, but it will not decide what a course is about,
because deciding what matters is the skill. It will not grade your answers
against a key, because the material is the reference and the judgement is
yours. It will not drop a topic because one session went well, because one
good session says little about next month. And it will not pre-make your
flashcards: writing a card in your own words is itself generative, and
retrieving it later is what keeps it.

**Per domain, never globally.** Calibration is tracked per course and per
kind of task. A single accuracy score would hide exactly the thing worth
knowing.

### Evidence base

Each of these shaped a feature or a constraint.

- **Roediger & Karpicke (2006); Karpicke & Roediger (2008).** Retrieval
  beats rereading over a week, and items dropped after a single correct recall
  are mostly forgotten. Study and review are retrieval first; nothing is
  retired after one success. *(Psychological Science 17(3); Science 319.)*
- **Richland, Kornell & Kao (2009); Kornell, Hays & Bjork (2009).** Attempting
  an answer before studying improves later recall even when the attempt is
  wrong, as long as the material follows. The un-skippable pre-test. *(JEP:
  Applied 15(3); JEP: LMC 35(4).)*
- **Dunlosky, Rawson, Marsh, Nathan & Willingham (2013).** Practice testing
  and distributed practice are the two high-utility techniques; self-explanation
  and interleaving are moderate; rereading and highlighting are low. Sessions
  are tests, reviews are spaced, self-explanation is offered and not
  required. *(Psychological Science in the Public Interest 14(1).)*
- **Rawson & Dunlosky (2011); Cepeda, Vul, Rohrer, Wixted & Pashler (2008).**
  Relearning on later days, with a first gap of about a day for a one-week
  horizon, is what durable retention costs. Review starts the next day and
  stretches from there. *(JEP: General 140(3); Psychological Science 19(11).)*
- **Bjork (1994).** Desirable difficulties: conditions that slow acquisition
  and improve retention, and the warning that judging learning by how a
  session felt is the illusion to avoid. *(In Metcalfe & Shimamura, eds.,
  Metacognition. MIT Press.)*
- **Koriat & Bjork (2005); Butterfield & Metcalfe (2001).** A judgement made
  with the answer in view is inflated, and confident errors are the most
  correctable ones. Predictions are committed before anything is revealed.
  *(JEP: LMC 31(2); JEP: LMC 27(6).)*
- **Rohrer & Taylor (2007); Brunmair & Richter (2019).** Mixing problem types
  lowered practice accuracy and more than tripled test scores a week later, and
  the meta-analysis shows the gain depends on the mixed material being
  confusable. Interleaving is a flag, not the default. *(Instructional Science
  35; Psychological Bulletin 145(11).)*
- **Piaget.** Knowledge is constructed, not received; a prediction that fails
  is an invitation to restructure. The loop's shape. *(The Psychology of
  Intelligence, 1950.)*
- **Wood, Bruner & Ross (1976); Pea (2004).** The first named what a tutor's
  support does; the second argued that support which never fades is not
  scaffolding. Chronos's estimation prompts fade as your record grows and your
  error drops. *(J. Child Psychol. Psychiat. 17; J. Learning Sciences 13(3).)*

---

## Architecture and stack

Ports and adapters: `domain/ports.py` defines the protocols the outbound
adapters implement, so the services that depend on them can be tested against
doubles and pointed at another LMS.

    src/sophia/
        api/            FastAPI app; routers/ is the HTTP surface, sessions.py the Redis session store
        adapters/       moodle (TUWEL), tiss, opencast/lecturetube, auth, whisper, embedder, chromadb, LLM
        domain/         models, ports, events, errors
        infra/          di.py composition root; engine, alembic, org_context, http, scheduler
        services/       athena_*, hermes_*, chronos, ingestion, study_questions, learning_events
        cli/            cyclopts: sophia auth|books|db|deadlines|jobs|lectures|plan|quickstart|register|status|study|worker
        worker/         claims ingestion jobs and runs the Hermes stages in the CUDA image
    frontend/           SvelteKit; src/routes is the page surface, src/lib/components the shared UI
    proxy/              Caddyfile: / → /app/, /app/* → frontend, /api/* → api
    docs/               accepted decision records

| Concern | Technology |
|---|---|
| Language | Python 3.12+, Pyright strict, ruff |
| API | FastAPI, Pydantic v2, structlog |
| Persistence | Postgres via asyncpg and SQLAlchemy with Alembic migrations; it also holds the processing queue and the study event log, streamed over SSE through LISTEN/NOTIFY. Redis for web sessions and the per-user stream cap |
| Lecture index | ChromaDB with sentence-transformers embeddings |
| Transcription | TUWEL captions where published, faster-whisper otherwise |
| CLI | cyclopts with Rich |
| Frontend | SvelteKit 2, Svelte 5, Paraglide JS i18n (see [docs/frontend-paraglide-decision.md](docs/frontend-paraglide-decision.md)) |
| Tests | pytest, respx, hypothesis; Vitest and Playwright with axe (WCAG 2.1 AA) |
| Packaging and CI | uv, hatchling, Docker Compose, GitLab CI |

Key decisions: protocol-based dependency injection; async I/O throughout;
every figure on the dashboard is inline SVG over a real table
([docs/frontend-dashboard-charts.md](docs/frontend-dashboard-charts.md));
the study surface's floors and scores are the server's, never the client's
([STUDY_SURFACE_SPEC.md](STUDY_SURFACE_SPEC.md)). Decision records in `docs/`
bind.

---

## Setup details

### Extras

| Extra | Installs | Needed for |
|---|---|---|
| `llm` | google-genai, groq | Gemini or Groq as the LLM provider |
| `hermes` | faster-whisper, chromadb, sentence-transformers, openai | Transcription, the lecture index, GitHub Models or Ollama |
| `index` | chromadb, sentence-transformers | Reading the index without transcribing (what the API image installs) |
| `athena` | genanki | Anki export |
| `pdf` | pymupdf | Course material PDFs |

`uv sync --all-extras --group dev` installs everything for development.

### LLM providers

One is enough. The setup wizard (`sophia lectures setup`) asks; environment
variables work too.

| Provider | Key | Notes |
|---|---|---|
| Gemini | `SOPHIA_GEMINI_API_KEY` from [AI Studio](https://aistudio.google.com/apikey) | Free tier, good default |
| Groq | `SOPHIA_GROQ_API_KEY` from [Groq Console](https://console.groq.com/keys) | Free tier, fast |
| GitHub Models | `GITHUB_TOKEN` | Through the `openai` package |
| Ollama | none | Local, transcripts never leave the machine; `ollama pull llama3.2`, served on `localhost:11434` |

### System tools

- **ffmpeg** strips the video after a download so only the audio is kept;
  without it the video file stays on disk. `apt install ffmpeg`,
  `brew install ffmpeg`, `winget install ffmpeg`.
- **NVIDIA drivers** make Whisper fast. Without a GPU everything runs on the
  CPU. The GPU is not available from the API container; the worker image has it
  ([DEPLOYMENT.md](DEPLOYMENT.md)).
- **A keyring backend** stores credentials. macOS and Windows have one; on
  Linux install `gnome-keyring` and `libsecret`. A headless box needs
  `PYTHON_KEYRING_BACKEND` pinned; see
  [docs/run-contract-setup.md](docs/run-contract-setup.md).
- **The OS scheduler** (systemd, launchd, Task Scheduler) runs
  `register --schedule`; nothing to install.

### Data access and privacy

Sophia reads TUWEL through its own AJAX API with your session cookie, TISS
through its public REST API, and falls back to parsing rendered HTML only where
no API exists. Your credentials go to TU Wien's SSO (`iu.zid.tuwien.ac.at`) and
nowhere else. Beyond `tuwel.tuwien.ac.at` and `tiss.tuwien.ac.at` it talks to
the lecture video hosts (`lecturetube.tuwien.ac.at`, `cdn.video.tuwien.ac.at`),
to Hugging Face once for the Whisper and embedding models, and to the LLM
provider you chose, which receives transcript passages for topic extraction
and questions; Ollama keeps those local. No telemetry, no analytics.

---

## Development

```bash
uv sync --all-extras --group dev
pnpm -C frontend install

uv run ruff check . && uv run ruff format --check . && pnpm -C frontend run lint
uv run pyright && pnpm -C frontend run check
pnpm -C frontend run test:unit          # fast, no services
make db.up && make test                 # the Python suite needs Postgres; 85 % coverage floor
make frontend.test                      # Vitest and Playwright
make frontend.a11y                      # axe against /app/*
```

`make docker-build` builds every default image, the CUDA worker included;
`make docker-build-api`, `make docker-build-frontend` and
`make docker-build-worker` build one. The CLI container sits behind a Compose
profile. CI runs lint, types, the Python suite against a Postgres service, the
OpenAPI contract check and the frontend checks (unit, size budget, a11y, e2e)
on merge requests and master; the API, frontend and proxy images build on
master and on demand in a merge request, and the worker image is built by
hand. Gate commands and their timings live in `.claude/gates.sh`.

The e2e suite runs against a fixture API, not the real server; a green
study-surface e2e test is evidence about the fixture until a parity suite
exists.

---

## Roadmap

Open work is tracked as issues under milestones on the project's GitLab.

- **Mid-Semester Essentials:** interleaved sessions, flashcards and the
  one-lecture session in the browser; the unified plan on the dashboard;
  deadlines that keep themselves current.
- **Pedagogy Fidelity:** the review reveals lecture passages to grade against;
  a reconciliation step after the numbers; calibration measured from delayed
  reviews, not in-session grades; confidence collected before every reveal;
  cards graded Again come back in the session; FSRS proper.
- **Browser Parity Backlog:** the Chronos estimate → timer → reflection loop,
  self-explanation, Anki export from the browser, maths rendering, pipeline
  settings, the quickstart gap moment.
- **Bücherwurm (unscheduled):** Open Access search, the download pipeline and
  a local library, and a usefulness prediction loop.

---

## Quick reference

```bash
# Authentication
uv run sophia auth login [--save-credentials]   # TUWEL + TISS; the secret makes re-login automatic
uv run sophia auth status
uv run sophia auth logout

# Registration (Kairos)
uv run sophia register favorites
uv run sophia register status 186.813
uv run sophia register groups 186.813
uv run sophia register go 186.813 --preferences "1,3" [--watch | --schedule]
uv run sophia jobs list | cancel <job-id>

# Lectures (Hermes)
uv run sophia lectures setup
uv run sophia lectures list
uv run sophia lectures process <module-id> [--materials]
uv run sophia lectures status <module-id>
uv run sophia lectures search "topic" <module-id> [--missed]
uv run sophia lectures download | transcribe | index <module-id>
uv run sophia lectures discard | restore | purge <module-id> <episode-id>
uv run sophia lectures mark-missed | unmark-missed <module-id> <episode-id>
uv run sophia lectures catch-up <module-id>
uv run sophia lectures materials <course-id>

# Study (Athena)
uv run sophia study topics <module-id>
uv run sophia study confidence <module-id>
uv run sophia study session <module-id> [topic] [--interleave] [--feedback-delay 30]
uv run sophia study review <module-id> [topic] [--interleave] [--count 20]
uv run sophia study explain <module-id> [topic]
uv run sophia study export <module-id> [--output f.apkg] [--deck-name N] [--blocked]
uv run sophia study due [module-id]

# Deadlines (Chronos)
uv run sophia deadlines sync | list [--horizon 30] [--sort urgency] | next | stress | graveyard
uv run sophia deadlines estimate <deadline-id>
uv run sophia deadlines track <deadline-id> --hours 2
uv run sophia deadlines timer start | stop <deadline-id>
uv run sophia deadlines done | reflect <deadline-id>
uv run sophia deadlines calibration
uv run sophia deadlines export-ics

# Everything at once
uv run sophia plan [--horizon 30] [--limit 20]
uv run sophia status
uv run sophia quickstart __call__ <module-id>   # the bare form does not parse yet
uv run sophia db status | upgrade

# Global flags
uv run sophia --json | --quiet | --no-color | --debug <command>
```

---

## Contributing

Sophia is a personal project; contributions from TU Wien students are
welcome. Open an issue describing what you want to work on, branch, write the
tests, and open a merge request. `ruff` and `pyright` in strict mode are the
style guide: if Pyright complains, that is a real issue.

## Acknowledgments

Sophia is named after the Greek word for wisdom (σοφία). The aim is not to
make students more efficient but wiser: better at knowing what they know, what
they do not, and what to do about the gap.

> *"I do not think I know what I do not know."* — Socrates, in Plato's *Apology* 21d
