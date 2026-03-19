# Sophia (Σοφία)

*"I am the love of wisdom, the spirit that kindles the flame of truth in those who seek it."*

A student toolkit for TU Wien that automates the tedious parts of academic life (getting a spot in the desired group, finding + aquiring textbooks, forcing yourself to confront unfamiliar fields of knowledge, tracking deadlines, analyzing exams) so you can focus on what matters: understanding.

**Status:** Early development (v0.1.0). Bücherwurm (book discovery), Kairos (group registration with scheduler), Hermes (lecture knowledge base with course material PDF indexing) and Athena (topic extraction, adaptive difficulty, FSRS spaced repetition, interleaved sessions, delayed feedback, confidence calibration, guided sessions, Anki export) are functional with 908 tests passing. Security hardening, CLI refactor (cyclopts), reliability/resilience improvements, UX polish (progress bars, status dashboard, quickstart), Docker support, and GitLab CI/CD are all in place. Bücherwurm download/library features are in progress. Chronos is planned.

| Abschnitt | Inhalt |
|-----------|--------|
| [Schnellstart: Kairos — Lehrveranstaltungsanmeldung](#schnellstart-kairos--lehrveranstaltungsanmeldung) | Kairos einrichten und automatische LV-Anmeldung planen |
| [Schnellstart: Hermes + Athena — Anki-Deck aus Vorlesungen](#schnellstart-hermes--athena--anki-deck-aus-vorlesungen) | Vorlesung verarbeiten und Lernkarten exportieren |
| [Getting Started: Kairos — Course Registration](#getting-started-kairos--course-registration) | Set up Kairos and schedule automatic course registration |
| [Getting Started: Hermes + Athena — Anki Deck from Lectures](#getting-started-hermes--athena--anki-deck-from-lectures) | Process a lecture and export flashcards |
| [What Sophia Does](#what-sophia-does) | The modules and what each one handles |
| [Philosophy](#philosophy-why-sophia-doesnt-just-do-everything-for-you) | Why Sophia makes you think instead of thinking for you |
| [Architecture](#architecture) | Hexagonal design, protocols, async |
| [Technology Stack](#technology-stack) | Languages, frameworks, tooling |
| [External Dependencies](#external-dependencies) | LLM providers, transcription, Anki, ffmpeg, and more |
| [Data Access](#data-access) | How Sophia talks to TUWEL and TISS |
| [Development](#development) | Running tests, linting, type checking |
| [Roadmap](#roadmap) | What's done, what's next |
| [Quick Reference](#quick-reference) | Common commands at a glance |
| [Contributing](#contributing) | How to help out |

---

## Schnellstart: Kairos — Lehrveranstaltungsanmeldung

Das ist Sophias stärkstes Feature. Anstatt um Mitternacht den Browser offen zu halten und F5 zu hämmern, installierst du einen System-Timer — und Sophia meldet dich auf TISS an, sobald das Fenster aufgeht. Du musst nicht mal wach sein.

> 💡 Schon Terminal, Python und uv installiert? Direkt zu [Schritt 4](#deutsch-schritt-4-sophia-installieren) springen.

### Schritt 1: Terminal öffnen

Ein Terminal ist eine textbasierte Oberfläche für deinen Computer — du tippst kurze Befehle statt Buttons zu klicken.

- **Windows 10/11:** `Win + R`, dann `wt` eingeben und Enter drücken. Falls das nicht klappt, nach „PowerShell" im Startmenü suchen.
- **macOS:** `Cmd + Space`, „Terminal" tippen, Enter.
- **Linux:** `Strg + Alt + T`, oder „Terminal" im App-Menü suchen.

✅ Ein Fenster mit einem blinkenden Cursor erscheint.

### Schritt 2: Python 3.12+ installieren

```bash
python3 --version
```

Wenn `Python 3.12.x` oder höher angezeigt wird — gut, weiter zu Schritt 3. Sonst Python von [python.org/downloads](https://www.python.org/downloads/) installieren.

> 💡 **Windows:** Beim Installieren das Häkchen bei **„Add Python to PATH"** setzen.

### Schritt 3: uv (Paketmanager) installieren

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Nach der Installation: Terminal schließen und neu öffnen.

✅ `uv --version` zeigt eine Versionsnummer.

### Schritt 4: Sophia installieren

```bash
git clone https://gitlab.com/mipkovich/sophia.git && cd sophia
uv sync
```

✅ Die Ausgabe endet mit etwas wie „Resolved ... packages".

### Schritt 5: Einloggen

```bash
uv run sophia auth login
```

Du wirst nach deinen TU Wien-Zugangsdaten gefragt (dieselben wie für TUWEL und TISS). Sophia speichert ein Session-Cookie lokal. Nichts wird weitergeleitet außer an TU Wiens eigene Server.

✅ Erfolgsmeldung mit deinem Namen erscheint.

### Schritt 6: Verfügbare Gruppen ansehen

```bash
uv run sophia register groups 186.813
```

Ersetze `186.813` durch deine LVA-Nummer. Sophia zeigt dir alle Gruppen mit Wochentag, Uhrzeit, Raum und aktuellem Belegungsstand.

### Schritt 7: Anmeldung planen — kein offenes Terminal nötig

Das ist der entscheidende Schritt. Dieser Befehl installiert einen systemweiten Timer (systemd unter Linux, launchd unter macOS, Aufgabenplanung unter Windows), der genau dann feuert, wenn das Anmeldefenster aufgeht:

```bash
uv run sophia register go 186.813 --preferences "1,3" --schedule
```

- `--preferences "1,3"` — deine Wunschreihenfolge (Indizes aus der Gruppen-Tabelle). Ist Gruppe 1 voll, versucht Sophia automatisch Gruppe 3.
- `--schedule` — kein offenes Terminal nötig. Sophia meldet sich selbst an.

```bash
uv run sophia jobs list              # geplante Jobs anzeigen
uv run sophia jobs cancel <job-id>   # Job stornieren
```

✅ Du bist fertig. Sophia kümmert sich um die Anmeldung.

### Problemlösungen

| Problem | Lösung |
|---------|--------|
| `command not found` nach uv-Installation | Terminal schließen und neu öffnen. |
| Python-Version zu alt | Python 3.12+ von [python.org](https://www.python.org/downloads/) installieren. Unter Linux: `sudo apt install python3.12`. |
| Login schlägt fehl | Zugangsdaten prüfen. Bei weiteren Fehlern: `uv run sophia auth login --debug`. |
| `git` nicht gefunden | Git von [git-scm.com/downloads](https://git-scm.com/downloads) installieren, dann Terminal neu starten. |

---

## Schnellstart: Hermes + Athena — Anki-Deck aus Vorlesungen

Dieser Leitfaden führt dich vom Einrichten bis zum fertigen Anki-Deck: Vorlesung herunterladen → transkribieren → Themen extrahieren → Lernkarten erstellen → als `.apkg` exportieren und in Anki importieren.

> 💡 Noch nicht eingerichtet? Erst [Schritte 1–4 oben](#deutsch-schritt-1-terminal-öffnen) durchführen und einloggen, dann hierher zurückkehren.

### Schritt A: Hermes/Athena-Abhängigkeiten installieren und konfigurieren

```bash
uv sync --extra hermes --extra llm --extra athena
uv run sophia lectures setup
```

Der Setup-Wizard erkennt deine GPU automatisch, empfiehlt ein passendes Whisper-Modell und fragt nach einem LLM-Anbieter für die Themenextraktion. Einmalig nötig.

**LLM-Anbieter wählen (einer reicht):**

| Anbieter | Kosten | Setup |
|----------|--------|-------|
| Gemini | Kostenloses Kontingent | API-Key von [aistudio.google.com](https://aistudio.google.com/apikey), in `.env` als `SOPHIA_GEMINI_API_KEY=...` eintragen |
| Groq | Kostenloses Kontingent | API-Key von [console.groq.com](https://console.groq.com/keys), als `SOPHIA_GROQ_API_KEY=...` |
| Ollama | Kostenlos, lokal | [Ollama](https://ollama.com/) installieren, `ollama pull llama3` ausführen — kein API-Key nötig |

### Schritt B: Vorlesungen entdecken

```bash
uv run sophia lectures list
```

Sophia zeigt alle Opencast-Aufzeichnungen deiner angemeldeten TUWEL-Kurse. Notiere dir die **Modul-ID** (erste Spalte).

### Schritt C: Vorlesung verarbeiten (eine Zeile)

```bash
uv run sophia lectures process <modul-id>
```

Führt die gesamte Pipeline aus: herunterladen → Stille erkennen → mit Whisper transkribieren → Vektoren einbetten und indizieren → Themen extrahieren. Je nach GPU und Länge der Aufzeichnungen dauert das 5–30 Minuten.

```bash
# Optional: Kurs-PDFs ebenfalls indizieren
uv run sophia lectures process <modul-id> --materials
```

> 💡 **Kurzform:** `uv run sophia quickstart <modul-id>` führt die gesamte Lernpipeline aus (verarbeiten → Themen → Selbsteinschätzung → Session → Export) und überspringt bereits abgeschlossene Schritte.

### Schritt D: Themen prüfen

```bash
uv run sophia study topics <modul-id>
```

Zeigt die extrahierten Themen an. Falls schon durch `lectures process` extrahiert, werden die vorhandenen Themen angezeigt. Ansonsten ruft Athena das LLM auf und extrahiert 5–15 akademische Themenbezeichnungen, verknüpft mit Vorlesungsabschnitten per semantischer Suche.

### Schritt E: Selbsteinschätzung

```bash
uv run sophia study confidence <modul-id>
```

Sophia fragt dich für jedes Thema: „Wie sicher bist du? (1–5)" — bevor du studiert hast. Diese Vorhersage ist der Startpunkt der Kalibrierung.

### Schritt F: Geführte Lernsession

```bash
uv run sophia study session <modul-id>
```

Sophia wählt automatisch das Thema mit dem größten blinden Fleck. Die Session läuft in drei Phasen: Pre-Test → Studieren der relevanten Vorlesungsabschnitte → Post-Test + Lernkartenerstellung. Du formulierst die Karten selbst.

### Schritt G: Anki-Deck exportieren

```bash
uv run sophia study export <modul-id>
```

Erzeugt `sophia-<modul-id>.apkg` im aktuellen Verzeichnis — bereit zum Import in Anki.

```bash
# Optionale Flags:
uv run sophia study export <modul-id> --output meine-karten.apkg
uv run sophia study export <modul-id> --deck-name "Algorithmen 2026S"
```

Anki von [apps.ankiweb.net](https://apps.ankiweb.net/) installieren, `.apkg` per Doppelklick importieren — fertig.

### Problemlösungen Hermes/Athena

| Problem | Lösung |
|---------|--------|
| `sophia lectures setup` läuft lange | Normal — beim ersten Mal werden Whisper und sentence-transformers heruntergeladen (1–5 GB). |
| GPU wird nicht erkannt | `nvidia-smi` prüfen. Unter WSL: WSL2 mit GPU-Passthrough aktivieren. Sophia fällt auf CPU zurück. |
| Keine Themen extrahiert | Sicherstellen, dass `sophia lectures process` abgeschlossen ist. LLM-Konfiguration mit `sophia lectures status` prüfen. |
| Anki-Export schlägt fehl | `uv sync --extra athena` ausführen — das `genanki`-Paket fehlt. |

---

## Getting Started: Kairos — Course Registration

This is Sophia's strongest feature. Instead of having your browser open at midnight mashing F5, you install a system timer — and Sophia submits your registration the instant the window opens. You don't even need to be awake.

> 💡 Already have a terminal, Python, and uv installed? Skip to [Step 4](#step-4-install-sophia).

### Step 1: Open a Terminal

A terminal (also called a command line, console, or shell) is a text-based interface to your computer. Instead of clicking buttons in a graphical window, you type short commands and press Enter.

- **Windows 10/11:** Press `Win + R`, type `wt`, and press Enter to open Windows Terminal. If that doesn't work, search for "PowerShell" in the Start menu.
- **macOS:** Press `Cmd + Space` to open Spotlight, type "Terminal", and press Enter.
- **Linux:** Press `Ctrl + Alt + T`, or find "Terminal" in your application menu.

✅ A window with a blinking cursor appears.

### Step 2: Install Python 3.12+

```bash
python3 --version
```

If you see `Python 3.12.x` or higher — great, move to Step 3. Otherwise install Python from [python.org/downloads](https://www.python.org/downloads/).

> 💡 **Windows:** During installation, check **"Add Python to PATH"** at the bottom of the first screen.

### Step 3: Install uv (the Package Manager)

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing, close and reopen your terminal.

✅ `uv --version` prints a version number.

### Step 4: Install Sophia

```bash
git clone https://gitlab.com/mipkovich/sophia.git && cd sophia
uv sync
```

✅ Output ends with something like "Resolved ... packages".

### Step 5: Log in

```bash
uv run sophia auth login
```

You'll be prompted for your TU Wien credentials — the same ones you use for TUWEL and TISS. Sophia saves a session cookie locally. Nothing is sent anywhere except to TU Wien's own servers.

✅ A success message with your name appears.

### Step 6: Browse available groups

```bash
uv run sophia register groups 186.813
```

Replace `186.813` with your course number. Sophia shows all groups with their day, time, location, and current enrollment.

### Step 7: Schedule registration — no open terminal needed

This is the key step. This command installs a system timer (systemd on Linux, launchd on macOS, Task Scheduler on Windows) that fires exactly when the registration window opens:

```bash
uv run sophia register go 186.813 --preferences "1,3" --schedule
```

- `--preferences "1,3"` — your priority order (indices from the groups table). If group 1 is full, Sophia automatically tries group 3.
- `--schedule` — no terminal needs to stay open. Sophia registers itself.

```bash
uv run sophia jobs list              # show scheduled jobs
uv run sophia jobs cancel <job-id>   # cancel a job
```

✅ Done. Sophia handles the registration.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `command not found` after installing uv | Close your terminal and open a new one. |
| Python version is too old | Install Python 3.12+ from [python.org](https://www.python.org/downloads/). On Linux: `sudo apt install python3.12`. |
| Login fails | Double-check your credentials. For more details: `uv run sophia auth login --debug`. |
| `git` not found | Install Git from [git-scm.com/downloads](https://git-scm.com/downloads), then restart your terminal. |

---

## Getting Started: Hermes + Athena — Anki Deck from Lectures

This guide takes you from setup to a finished Anki deck: download a lecture → transcribe → extract topics → build flashcards → export as `.apkg` and import into Anki.

> 💡 Not set up yet? Run [Steps 1–4 above](#step-1-open-a-terminal) and log in first, then come back here.

### Step A: Install Hermes/Athena dependencies and configure

```bash
uv sync --extra hermes --extra llm --extra athena
uv run sophia lectures setup
```

The setup wizard auto-detects your GPU, recommends a Whisper model, and asks you to pick an LLM provider for topic extraction. Run once.

**Pick one LLM provider:**

| Provider | Cost | Setup |
|----------|------|-------|
| Gemini | Free tier | Get key at [aistudio.google.com](https://aistudio.google.com/apikey), add `SOPHIA_GEMINI_API_KEY=...` to `.env` |
| Groq | Free tier | Get key at [console.groq.com](https://console.groq.com/keys), add `SOPHIA_GROQ_API_KEY=...` |
| Ollama | Free, local | Install [Ollama](https://ollama.com/), run `ollama pull llama3` — no API key needed |

### Step B: Discover lecture recordings

```bash
uv run sophia lectures list
```

Sophia shows all Opencast recordings from your enrolled TUWEL courses. Note the **module ID** (first column).

### Step C: Process the lecture (one command)

```bash
uv run sophia lectures process <module-id>
```

Runs the full pipeline: download → silence detection → transcribe with Whisper → embed and index → extract topics. Depending on your GPU and recording length, expect 5–30 minutes.

```bash
# Optional: also index course material PDFs
uv run sophia lectures process <module-id> --materials
```

> 💡 **Shortcut:** `uv run sophia quickstart <module-id>` runs the entire study pipeline (process → topics → confidence → session → export) and skips any steps already completed.

### Step D: Check topics

```bash
uv run sophia study topics <module-id>
```

Shows extracted topics. If already extracted by `lectures process`, displays the existing topics. Otherwise, Athena calls the LLM to extract 5–15 academic topic labels and cross-references them with lecture segments via semantic search.

### Step E: Rate your confidence

```bash
uv run sophia study confidence <module-id>
```

Sophia asks you to rate each topic 1–5 *before* you've studied it. This prediction is the baseline for calibration.

### Step F: Guided study session

```bash
uv run sophia study session <module-id>
```

Sophia auto-selects the topic where your gap is largest. The session runs: pre-test → study the relevant lecture segments → post-test + flashcard creation. You write the cards in your own words.

### Step G: Export to Anki

```bash
uv run sophia study export <module-id>
```

Generates `sophia-<module-id>.apkg` in the current directory, ready to import into Anki.

```bash
# Optional flags:
uv run sophia study export <module-id> --output my-cards.apkg
uv run sophia study export <module-id> --deck-name "Algorithms 2026S"
```

Install Anki from [apps.ankiweb.net](https://apps.ankiweb.net/), double-click the `.apkg` to import — done.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `sophia lectures setup` is slow | Normal — Whisper and sentence-transformers download on first run (1–5 GB). |
| GPU not detected | Run `nvidia-smi`. On WSL, you need WSL2 with GPU passthrough. Sophia falls back to CPU. |
| No topics extracted | Make sure `sophia lectures process` completed. Check LLM config with `sophia lectures status`. |
| Anki export fails | Run `uv sync --extra athena` — the `genanki` package is missing. |

---

## What Sophia Does

Sophia is organized into modules, each named for a concept that matches its purpose:

| Module | Command | What It Does | Status |
|--------|---------|--------------|--------|
| **Bücherwurm** 📚 | `sophia books` | Discovers textbook references from enrolled TUWEL courses (ISBN extraction, metadata enrichment) | ✅ Discovery |
| **Kairos** ⚡ | `sophia register` | Automates TISS course and group registration with preference lists — seize the right moment | ✅ Functional |
| **Hermes** 🎙️ | `sophia lectures` | Lecture knowledge base: download recordings, silence detection, transcribe with Whisper, semantic search, course material PDF scraping and indexing, discard/restore/purge management | ✅ Functional |
| **Chronos** ⏰ | `sophia deadlines` | Deadline coach that helps you estimate effort, prioritize tasks, and reflect on what worked | 📋 Planned |
| **Athena** 🎓 | `sophia study` | Study layer over Hermes: LLM topic extraction, confidence calibration, adaptive difficulty (cued/explain/transfer questions), guided pre/post-test sessions, FSRS-inspired adaptive spaced repetition, interleaved multi-topic sessions, delayed feedback with reflection countdown, no-skip pre-test for generation effect, self-explanation, Anki `.apkg` export | ✅ Functional |
| **Quickstart** 🚀 | `sophia quickstart` | Chains the full study pipeline (process → topics → confidence → session → export), skipping already-completed steps | ✅ Functional |
| **Status** 📊 | `sophia status` | Cross-course dashboard showing lectures, topics, flashcards, and reviews due across all courses | ✅ Functional |

### Bücherwurm in Action

Bücherwurm (German for "bookworm") scans your enrolled TUWEL courses and extracts every textbook reference it can find — from course descriptions, uploaded syllabi, and resource sections. Today it:

1. Scans enrolled TUWEL courses via the Moodle AJAX API
2. Extracts textbook references from course descriptions, syllabi, and resources
3. Resolves ISBNs and enriches metadata (title, authors, edition) via TISS
4. Presents a table with title, authors, ISBN, source, and course

**What's coming (M1 — in progress):** Open Access and Anna's Archive search, download pipeline with local library organized by semester, and a usefulness prediction loop where Sophia asks you to predict whether each book will be useful before downloading — then revisits that prediction after a few weeks.

### Kairos in Action

Kairos (Καιρός — the decisive, opportune moment) automates course registration on TISS. Instead of frantically refreshing the page when a registration window opens, Kairos watches the clock and submits the instant the window opens — with a preference-ordered list of groups so you get your best available slot.

**Step 1: Log in to TISS**

```bash
uv run sophia auth login
```

This authenticates with both TUWEL and TISS using your TU Wien credentials. Your sessions are stored locally.

**Step 2: Browse available groups**

```bash
uv run sophia register groups 186.813
```

Sophia shows you a table of all groups with their schedule at a glance:

```
                        Groups for 186.813 (2026S)
┏━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┓
┃ # ┃ Name         ┃ Day       ┃ Time        ┃ Location ┃ Enrolled ┃ Capacity ┃ Status   ┃
┡━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
│ 1 │ Group 1 - Mo │ Monday    │ 09:00–11:00 │ Room A   │       15 │       30 │ open     │
│ 2 │ Group 2 - Di │ Tuesday   │ 14:00–16:00 │ HS1      │       30 │       30 │ full     │
│ 3 │ Group 3 - Mi │ Wednesday │ 10:00–12:00 │ Lab      │       20 │       25 │ open     │
└───┴──────────────┴───────────┴─────────────┴──────────┴──────────┴──────────┴──────────┘
```

Use this to decide which groups fit your schedule, then set your preference order.

**Step 3: Register with preferences**

```bash
# Register for LVA (course itself)
uv run sophia register go 186.813

# Register with group preferences (indices from the table above)
uv run sophia register go 186.813 --preferences "1,3"
```

If group 1 is full, Kairos automatically tries group 3. You get the best available slot from your preference list.

**Step 4: Watch mode — wait for the window to open**

```bash
uv run sophia register go 186.813 --preferences "1,3" --watch
```

Kairos checks the registration status, calculates when the window opens, sleeps until the right moment, and submits the instant it opens. Run this in a terminal tab (or `tmux`/`screen` session) before the registration window opens and walk away.

**Step 5: Schedule it — no terminal needed**

```bash
uv run sophia register go 186.813 --preferences "1,3" --schedule
```

This installs a system timer (systemd on Linux, launchd on macOS, Task Scheduler on Windows) that fires at the registration window. No terminal needs to stay open.

```bash
uv run sophia jobs list              # show scheduled jobs
uv run sophia jobs cancel <job-id>   # cancel a job
```

### Hermes in Action

Hermes (Ἑρμῆς — the messenger who carries knowledge between realms) turns lecture recordings into a searchable knowledge base. It downloads recordings from TUWEL's Opencast integration, transcribes them using Whisper (with GPU acceleration and hallucination filtering), and builds a semantic search index so you can find exactly where a topic was discussed.

**The pipeline:**

1. **`sophia lectures setup`** — detect hardware (GPU/CPU), choose Whisper model, configure LLM and embedding providers
2. **`sophia lectures list`** — discover lecture recordings from enrolled courses
3. **`sophia lectures process <module-id>`** — run the full pipeline in one command: download → silence detection → transcribe → index → extract topics
4. **`sophia lectures search "topic" <module-id>`** — semantic search within a lecture's transcripts
5. **`sophia lectures materials <course-id>`** — scrape and list course material PDFs from TUWEL; with `--index` to embed and index them in ChromaDB

Or run each stage individually:

- **`sophia lectures download <module-id>`** — download recordings (prefers audio for efficiency); silently skips empty recordings detected by ffmpeg silence analysis
- **`sophia lectures transcribe <module-id>`** — transcribe with Whisper, VAD filtering, hallucination detection
- **`sophia lectures index <module-id>`** — chunk transcripts and build embedding index

Step 1 only needs to happen once. The setup wizard detects your GPU, recommends a Whisper model based on VRAM, lets you choose an LLM provider (GitHub Models, Gemini, Groq, or Ollama), and automatically installs the heavy dependencies (`faster-whisper`, `chromadb`, `sentence-transformers`) when needed.

**Lecture management:**

- **`sophia lectures status <module-id>`** — per-episode table showing download, transcription, index status, and the skip reason for any silently-detected empty recordings
- **`sophia lectures discard <module-id> <episode-id>`** — manually mark an episode as discarded so it won't be processed again
- **`sophia lectures restore <module-id> <episode-id>`** — undo a discard and re-queue the episode for processing
- **`sophia lectures purge <module-id> <episode-id>`** — remove all indexed content for an episode from the knowledge base (ChromaDB chunks, transcript segments, index records)

### Athena in Action

Athena (Ἀθηνᾶ — goddess of wisdom and strategy) turns Hermes's indexed lecture transcripts into an active study workflow. Hermes is responsible for getting the knowledge in; Athena is responsible for getting it into your head.

**Division of labour between Hermes and Athena:**

| Responsibility | Module |
|---------------|--------|
| Download and transcribe recordings | Hermes |
| Build the semantic search index (ChromaDB) | Hermes |
| Detect silence, skip empty lectures | Hermes |
| Scrape and index course material PDFs | Hermes (`lectures materials`) |
| Call the LLM to extract topic labels from transcripts | Athena (`study topics`) |
| Cross-reference topics with lecture chunks via embedding search | Athena (`study topics`) |
| Track confidence predictions per topic | Athena (`study confidence`) |
| Run guided pre-test → study → post-test sessions | Athena (`study session`) |
| Adaptive difficulty based on confidence | Athena (`study session`) |
| Interleaved multi-topic sessions | Athena (`study session --interleave`) |
| Delayed feedback with reflection countdown | Athena (`study session`) |
| FSRS-inspired adaptive spaced repetition | Athena (`study review`) |
| Generate and schedule flashcard spaced review | Athena (`study review`) |
| Self-explanation exercises for wrong answers | Athena (`study explain`) |
| Export flashcard deck as Anki `.apkg` | Athena (`study export`) |

Athena does not re-download or re-transcribe anything. It reads directly from what Hermes has already indexed. Running `sophia lectures process <module-id>` is the only prerequisite.

**Anki export detail:** `sophia study export <module-id>` generates a `.apkg` deck file using `genanki`. Cards are tagged by topic and source (lecture/session), and the deck is shuffled by default so topics are interleaved (better for long-term retention than blocked review). Use `--output` and `--deck-name` to customise. Use `--blocked` to group cards by topic instead of interleaving.

**Pedagogical features:**

- **Adaptive difficulty:** Sessions adapt question difficulty based on your confidence — low confidence gets cued/recognition questions, mid-range gets explanation questions, high confidence gets transfer/application questions. This keeps sessions in Vygotsky's zone of proximal development.
- **FSRS scheduling:** Spaced repetition uses an FSRS-inspired algorithm that adjusts difficulty and stability parameters per topic, producing adaptive intervals instead of fixed ones. Replaces the basic scheduler from earlier versions.
- **Interleaved sessions:** The `--interleave` flag mixes 2–3 topics in one session, prioritizing blind spots (lowest confidence topics), for better discrimination and transfer. Evidence from cognitive science shows interleaving produces stronger long-term retention than blocked practice.
- **Delayed feedback:** After the post-test, a configurable countdown (default 30 seconds, set with `--feedback-delay`) with reflection prompts before showing results — forces metacognitive processing instead of pattern-matching.
- **No-skip pre-test:** Pre-test questions require an answer (even a guess) to leverage the generation effect — wrong attempts strengthen subsequent encoding of the correct answer.
- **Course materials:** `sophia lectures process --materials` scrapes TUWEL course PDFs, chunks them, and indexes them in ChromaDB alongside lecture transcripts for richer RAG context during study sessions.

### What's Coming: Chronos

**Chronos** will pull assignment deadlines from TUWEL and TISS, but it won't just list them in a calendar. TUWEL already does that, and students still miss deadlines. The problem isn't information, it's planning. Chronos asks you to estimate how long each task will take *before* you start, tracks your actual time, and helps you see where your estimates fall short. Over a semester, you develop better planning intuition, a skill that transfers far beyond university.

---

## Philosophy: Why Sophia Doesn't Just Do Everything for You

It would be easy to build a tool that auto-generates study plans, pre-makes flashcards, and tells students exactly what to do. Many edtech products do precisely this, optimizing for the feeling of productivity rather than actual learning. Sophia deliberately does none of these things. The reason has to do with how learning actually works, and decades of cognitive science research point in the same direction.

### Maieutics (The Socratic Midwife)
Sophia is named for wisdom, but her methodology is Socratic. In the Meno, Socrates famously compares himself to a midwife: he cannot give birth to the truth for the student, but he can help the student deliver it themselves.

"The boy now knows what it is to be in doubt... and while he does not know, he at least does not think he knows." — Meno 84a

Sophia uses Piaget’s equilibration theory to modernise this ancient practice. We provide the "scaffold" (the data, the prompts, the timing), but the construction of the knowledge remains entirely yours.

### The Constructivist Foundation

Sophia is built on Jean Piaget's constructivist epistemology: the idea that knowledge is not passively received but actively constructed through experience. A student who reads a summary is not doing the same cognitive work as a student who wrestles with the material and builds their own understanding. The summary might transmit information, but information is not knowledge. Knowledge requires the learner to integrate new ideas with existing schemas, to assimilate where possible and accommodate where necessary.

This has real design consequences. Every feature passes through a filter: *does this help the student construct understanding, or does it bypass thinking?* If a feature does the thinking for you, it doesn't ship.

> *"The principal goal of education in the schools should be creating men and women who are capable of doing new things, not simply repeating what other generations have done."*
> — Piaget, in Bringuier, J.-C. (1980). *Conversations with Jean Piaget* (B. M. Gulati, Trans.). University of Chicago Press, p. 132.

### The Predict → Act → Reflect Cycle

All three modules share a common metacognitive pattern inspired by Piaget's equilibration theory. The cycle works like this:

1. **Predict.** Before an action, Sophia asks you to commit to a prediction. Before downloading a book, it asks: *will this actually be useful for your course?* Before a deadline, it asks: *how many hours do you think this will take?*
2. **Act.** You do the work: read the book, complete the assignment, study for the exam.
3. **Reflect.** Afterward, Sophia asks you to compare your prediction with reality. Was the book useful? How long did the assignment actually take? Which exam topics surprised you?

The delta between prediction and reality creates *disequilibrium*, the cognitive conflict that Piaget identified as the engine of intellectual development. When your mental model fails to predict reality, you're forced into *accommodation*: restructuring your schemas to better fit the world. This is uncomfortable, and it is exactly where learning happens.

There are no points, no streaks, no leaderboards. The reward is watching your predictions get more accurate over time and seeing the gap between expectation and reality narrow. That narrowing gap is proof you're building better mental models of how you learn.

> *"Every time we teach a child something, we keep him from inventing it himself. On the other hand, that which we allow him to discover for himself will remain with him visible for the rest of his life."*
> — Piaget

### What Sophia Deliberately Won't Do

Sophia will never auto-generate a study plan, because planning *is* the skill. The act of looking at your deadlines, estimating effort, and deciding what to prioritize is a form of metacognitive practice that you can't outsource without losing the benefit.

It won't pre-make flashcards, because writing them requires elaborative encoding. The act of transforming material into your own words forces you to decide what matters, how to phrase it, and what connections to draw. A pre-made flashcard skips all of that cognitive work.

It won't eliminate difficulty, because difficulty is where learning happens. Bjork and Bjork (1992) call these "desirable difficulties": conditions that slow initial performance but enhance long-term retention and transfer. Spacing, interleaving, retrieval practice, and generation effects all share this property. They feel harder in the moment but produce more durable learning.

Planning, predicting, and reflecting is not overhead. It IS the learning.

Sophia's UI is intentionally minimal for the same reason. A polished dashboard full of charts can create the illusion of productivity. Sophia shows you data, asks you questions, and gets out of the way.

### Per-Domain Calibration (Horizontal Décalage)

When Sophia tracks your prediction accuracy, it does so per domain, never globally. A student might be excellently calibrated for programming assignments while being wildly miscalibrated for mathematical proofs. Averaging these into a single score would hide what matters.

This mirrors Piaget's concept of *horizontal décalage*: the observation that cognitive abilities don't develop uniformly across all domains. You can be formal-operational in one area and concrete-operational in another. Sophia respects this by maintaining separate calibration profiles for each course and task type.

In practice, this means your Sophia dashboard might show something like: "Your effort estimates for programming assignments are within 15% of actual time, but your exam confidence for proofs is miscalibrated by 40%." That specificity is what makes it useful. A blended average tells you nothing.

### Evidence Base

Sophia's design draws on well-established research in cognitive and learning science. Each of these directly shaped a feature or a design constraint:

- **Piaget:** Constructivism and equilibration — knowledge is built through prediction, conflict, and accommodation. This gives Sophia its core loop: predict → act → reflect. *(Piaget, J. (1950). The Psychology of Intelligence. Routledge & Kegan Paul.)*
- **Vygotsky:** Zone of proximal development — effective tools scaffold what's currently too hard and fade support as competence grows. Sophia's prompts become less frequent as your calibration improves. *(Vygotsky, L. S. (1978). Mind in Society: The Development of Higher Psychological Processes. Harvard University Press.)*
- **Bjork & Bjork (1992):** Desirable difficulties — conditions that make learning harder in the short term (spacing, interleaving, retrieval practice) enhance long-term retention and transfer. Sophia never optimizes for short-term ease. *(Bjork, R. A. (1994). Memory and metamemory considerations in the training of human beings. In J. Metcalfe & A. Shimamura (Eds.), Metacognition: Knowing about Knowing (pp. 185–205). MIT Press.)*
- **Kapur (2008):** Productive failure — students who struggle with a problem before receiving instruction develop deeper conceptual understanding than those given instruction first. Sophia lets you struggle with predictions before showing data. *(Kapur, M. (2008). Productive failure. Cognition and Instruction, 26(3), 379–424. https://doi.org/10.1080/07370000802212669)*
- **Dunlosky et al. (2013):** Comprehensive review of learning strategies — self-explanation and practice testing ranked as the highest-utility strategies. Sophia emphasizes both. *(Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013). Improving students' learning with effective learning techniques. Psychological Science in the Public Interest, 14(1), 4–58. https://doi.org/10.1177/1529100612453266)*
- **Roediger & Karpicke (2006):** The testing effect — retrieving information from memory strengthens retention more than re-reading it. Athena's flashcard system is built entirely on retrieval practice. *(Roediger, H. L., III, & Karpicke, J. D. (2006). Test-enhanced learning: Taking memory tests improves long-term retention. Psychological Science, 17(3), 249–255. https://doi.org/10.1111/j.1467-9280.2006.01693.x)*

---

## Architecture

Sophia follows a hexagonal (ports and adapters) architecture. The domain core has zero external dependencies. It defines protocols (Python's structural typing) that adapters implement. This means the business logic never knows whether it's talking to a real TUWEL server, a mock in a test, or a completely different LMS. Any adapter can be swapped without touching a single line of business logic.

```
src/sophia/
├── __init__.py
├── __main__.py
├── py.typed
├── config.py
├── cli/              # Command-line interface (cyclopts)
│   ├── __init__.py
│   ├── _output.py    # Shared output formatting (JSON, table, quiet mode)
│   ├── _resolver.py  # Module ID → course ID resolution
│   ├── auth.py       # sophia auth login/status/logout
│   ├── books.py      # sophia books discover
│   ├── jobs.py       # sophia jobs list/cancel
│   ├── lectures.py   # sophia lectures setup/list/process/download/transcribe/index/search/status/discard/restore/purge/materials
│   ├── quickstart.py # sophia quickstart <module-id>
│   ├── register.py   # sophia register favorites/status/groups/go
│   ├── run_job.py    # Internal: sophia _run-job
│   ├── status.py     # sophia status (cross-course dashboard)
│   └── study.py      # sophia study topics/confidence/session/review/explain/export/due
├── domain/           # Pure models, protocols, domain events
│   ├── models.py     # Book, Course, TopicMapping, KnowledgeChunk, StudySession, StudentFlashcard, ReviewSchedule, ConfidenceRating, CourseMaterial, DifficultyLevel, MaterialSource, etc.
│   ├── ports.py      # Protocol definitions (CourseProvider, BookSearcher, ...)
│   ├── events.py     # Domain events (BookFound, TopicsExtracted, StudySessionCompleted, ...)
│   └── errors.py     # Domain-specific error hierarchy
├── services/         # Orchestration and business logic
│   ├── pipeline.py   # Book discovery pipeline
│   ├── reference_extractor.py
│   ├── resource_classifier.py
│   ├── registration.py        # Kairos preference-based registration
│   ├── job_runner.py          # Cross-platform job scheduler (systemd/launchd/Task Scheduler)
│   ├── hermes_setup.py        # Hardware detection, config wizard
│   ├── hermes_download.py     # Lecture download with audio extraction and silence detection
│   ├── hermes_transcribe.py   # Whisper transcription with VAD and hallucination filtering
│   ├── hermes_index.py        # Chunking, embeddings, semantic search orchestration
│   ├── hermes_manage.py       # Discard/restore/purge and pipeline status
│   ├── hermes_pipeline.py     # E2E pipeline orchestration (download → silence detection → transcribe → index → extract topics)
│   ├── material_index.py      # Course material (PDF) scraping and ChromaDB indexing
│   ├── athena_study.py        # Topic extraction, lecture-material cross-linking, question generation
│   ├── athena_session.py      # Guided study sessions: adaptive difficulty, interleaved review, delayed feedback
│   ├── athena_confidence.py   # Confidence rating, calibration tracking, difficulty mapping
│   ├── athena_review.py       # FSRS-inspired adaptive spaced repetition scheduling
│   └── athena_export.py       # Anki .apkg deck generation (genanki)
├── adapters/         # External world implementations
│   ├── moodle.py     # TUWEL/Moodle AJAX adapter
│   ├── tiss.py       # TISS public API adapter
│   ├── tiss_registration.py   # TISS registration (JSF scraping)
│   ├── auth.py                # SSO authentication flow
│   ├── lecturetube.py         # TUWEL Opencast lecture discovery
│   ├── lecture_downloader.py  # Recording download adapter
│   ├── transcriber.py         # Whisper adapter (faster-whisper)
│   ├── embedder.py            # Embedding adapter (sentence-transformers)
│   ├── knowledge_store.py     # Vector store adapter (ChromaDB)
│   └── topic_extractor.py     # LLM topic extraction (Gemini/Groq/GitHub Models/Ollama)
├── infra/            # Cross-cutting concerns
│   ├── http.py       # Shared HTTP client with retry logic
│   ├── persistence.py # SQLite via aiosqlite (with 16 migrations)
│   ├── di.py         # Dependency injection container
│   ├── logging.py    # Structured logging (structlog)
│   ├── scheduler.py  # OS-native job scheduler (systemd/launchd/Task Scheduler)
│   └── migrations/   # Schema migrations (001–016)
```

Key design decisions:

- **Protocol-based dependency injection.** Services depend on protocols (`typing.Protocol`), not concrete implementations. The DI container wires adapters to protocols at startup. This makes the system both testable (swap in mocks) and extensible (add new adapters without touching services).
- **Domain events.** State changes emit events (`BookFound`, `TopicsExtracted`, `StudySessionCompleted`, etc.) that other components can react to, keeping modules decoupled and enabling future features like activity logging.
- **Async throughout.** All I/O is async via `httpx` and `aiosqlite`, so multiple courses are scanned concurrently.
- **Strict type checking.** Pyright in strict mode catches errors at development time. Combined with Pydantic models for runtime validation, the system is robust at both layers.

---

## Technology Stack

| Concern | Technology |
|---------|------------|
| Language | Python 3.12+ with strict type annotations |
| HTTP | httpx (async) with tenacity retry logic |
| Data models | Pydantic v2 for validation, serialization |
| Persistence | SQLite via aiosqlite |
| CLI | cyclopts with Rich formatting |
| Logging | structlog (structured, JSON-capable) |
| Testing | pytest, pytest-asyncio, respx, hypothesis |
| Linting | ruff |
| Type checking | Pyright (strict mode) |
| Packaging | uv + hatchling |
| CI | GitLab CI |

---

## External Dependencies

Sophia pulls in several external tools and services beyond the core Python stack. Some are Python packages installed automatically with `uv sync`, others are optional extras you opt into, and a few are system-level tools you install separately. This section tells you what each one does, whether you need it, and how to get it running on your platform.

### At a Glance

| Dependency | What It Does for Sophia | Required? | How to Install |
|-----------|------------------------|-----------|----------------|
| keyring | Stores your TUWEL/TISS credentials securely in your OS keychain | Core (auto-installed) | `uv sync` |
| google-genai | Calls Google Gemini for topic extraction from lectures | Optional | `uv sync --extra llm` |
| groq | Calls Groq for fast topic extraction (alternative to Gemini) | Optional | `uv sync --extra llm` |
| faster-whisper | Transcribes lecture recordings (speech-to-text) | Optional | `uv sync --extra hermes` |
| sentence-transformers | Encodes text into vectors for semantic search over lectures | Optional | `uv sync --extra hermes` |
| chromadb | Stores and searches lecture embeddings (vector database) | Optional | `uv sync --extra hermes` |
| openai | Connects to GitHub Models or local Ollama for topic extraction | Optional | `uv sync --extra hermes` |
| genanki | Generates Anki flashcard decks (`.apkg` files) | Optional | `uv sync --extra athena` |
| ffmpeg | Extracts audio from lecture videos (system tool) | Optional (system) | See [System Tools](#5-system-tools) |
| NVIDIA drivers | GPU acceleration for Whisper transcription | Optional (system) | See [System Tools](#5-system-tools) |

### 1. Core (Always Installed)

These are installed automatically when you run `uv sync`.

**keyring** (≥ 25.0) — OS-level credential storage. Used by Sophia's auth adapter to store your TUWEL and TISS session credentials securely instead of in a plain-text file.

| Platform | Backend | Setup Needed? |
|----------|---------|---------------|
| macOS | Keychain | None — built-in |
| Windows | Credential Manager | None — built-in |
| Linux | SecretStorage (via libsecret / gnome-keyring) | You may need to install the backend |

**Linux users:** If Sophia warns about missing keyring backends, install the system libraries:

```bash
# Debian / Ubuntu
sudo apt install gnome-keyring libsecret-1-0

# Fedora / RHEL
sudo dnf install gnome-keyring libsecret

# Arch
sudo pacman -S gnome-keyring libsecret
```

If no keyring backend is available, Sophia falls back gracefully — you'll just be prompted for credentials more often.

### 2. LLM Providers (Optional)

Install with:

```bash
uv sync --extra llm
```

These packages let Sophia use large language models to extract study topics from lecture transcripts. You only need **one** provider — pick whichever you prefer.

| Package | Provider | API Key Env Var | Get a Key |
|---------|----------|----------------|-----------|
| google-genai (≥ 1.0) | Google Gemini | `SOPHIA_GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) |
| groq (≥ 0.4) | Groq (fast inference) | `SOPHIA_GROQ_API_KEY` | [Groq Console](https://console.groq.com/keys) |

> **GitHub Models / Ollama:** The `openai` package (used for GitHub Models and Ollama providers) is bundled in the `hermes` extra (`uv sync --extra hermes`), not in `llm`. If you only need Gemini or Groq, `--extra llm` is sufficient.

**Which one should I pick?**

- **Gemini** — generous free tier, good quality. Best default choice.
- **Groq** — extremely fast inference, free tier available. Good if you value speed.
- **Ollama** (via the openai package, included in `hermes` extra) — runs entirely on your machine, no API key needed, no data leaves your computer. Requires [Ollama](https://ollama.com/) installed separately. Best for privacy-conscious users or offline use.

All three produce comparable results for Sophia's use case (topic extraction). You can switch providers at any time.

### 3. Hermes — Lecture Knowledge Base (Optional)

Install with:

```bash
uv sync --extra hermes
```

These power Sophia's lecture transcription and semantic search features.

**faster-whisper** (≥ 1.1) — Optimized Whisper speech-to-text engine. Transcribes your lecture recordings into searchable text. Downloads a model on first use (1–3 GB depending on the model size Sophia picks for your hardware).

- Works on all platforms with no special setup.
- **GPU acceleration:** If you have an NVIDIA GPU with CUDA, Whisper runs dramatically faster. Sophia auto-detects your GPU and picks the right model size. Without a GPU, it still works — just slower.

**sentence-transformers** (≥ 3.0) — Encodes lecture text into vector embeddings so Sophia can search lectures by *meaning*, not just keywords. Pulls in PyTorch as a dependency (large download, ~2 GB on first install). No platform-specific setup required.

**chromadb** (≥ 1.0) — A SQLite-backed vector database that stores and searches the lecture embeddings locally. No platform-specific setup required.

**openai** (≥ 1.50) — Included in the `hermes` extra for GitHub Models and Ollama provider support. If you use Gemini or Groq exclusively, you don't need this — but it's installed automatically with `--extra hermes`.

### 4. Athena — Study & Export (Optional)

Install with:

```bash
uv sync --extra athena
```

**genanki** (≥ 0.13) — Generates `.apkg` Anki flashcard deck files from Sophia's study materials. Used by `sophia study export` to create ready-to-import flashcard decks.

To actually *use* the generated decks, you need **Anki** installed separately:

| Platform | Install Anki |
|----------|--------------|
| All platforms | Download from [apps.ankiweb.net](https://apps.ankiweb.net/) |
| Linux | Also available via `sudo apt install anki` or Flatpak |
| Android | [AnkiDroid](https://play.google.com/store/apps/details?id=com.ichi2.anki) (free) on Google Play |
| iOS | [AnkiMobile](https://apps.apple.com/app/ankimobile-flashcards/id373493387) on the App Store |

### 5. System Tools

These are **not** Python packages — you install them through your operating system's package manager. All are optional; Sophia works without them but with reduced functionality.

#### ffmpeg

Extracts audio tracks from lecture video recordings so Sophia downloads only the audio (much smaller) instead of full video files. Sophia detects ffmpeg automatically; if it's missing, it simply downloads the complete video instead.

| Platform | Install Command |
|----------|----------------|
| Debian / Ubuntu | `sudo apt install ffmpeg` |
| Fedora / RHEL | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |
| macOS | `brew install ffmpeg` |
| Windows | `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH |

#### NVIDIA Drivers + CUDA (for GPU-accelerated transcription)

Sophia's Hermes module detects your GPU via `nvidia-smi` to choose the optimal Whisper model. Without a GPU, everything still works — Sophia just uses CPU mode.

| Platform | Install |
|----------|---------|
| Debian / Ubuntu | `sudo apt install nvidia-driver-XXX` (replace XXX with your version, e.g. 550) |
| Fedora / RHEL | `sudo dnf install akmod-nvidia` |
| Windows | Download from [nvidia.com/drivers](https://www.nvidia.com/drivers) |
| macOS | Not applicable (no CUDA support on macOS) |

#### System Scheduler (for `sophia register --schedule`)

Sophia's Kairos module can schedule automatic registration attempts. It uses your OS's built-in scheduler:

| Platform | Scheduler | Setup Needed? |
|----------|-----------|---------------|
| Linux | systemd timers | None — systemd is pre-installed on most distros |
| macOS | launchd | None — built-in |
| Windows | Task Scheduler | None — built-in |

### 6. Configuration

After installing dependencies, configure your LLM provider:

**Option A: Interactive wizard** (recommended)

```bash
sophia lectures setup
```

This walks you through choosing a provider, entering API keys, and picking model sizes for your hardware. All settings are saved locally.

**Option B: Environment variables**

Create a `.env` file in the project root or set these in your shell:

```bash
# Pick one (or more) — Sophia uses whichever is configured
SOPHIA_GEMINI_API_KEY=your-gemini-key-here
SOPHIA_GROQ_API_KEY=your-groq-key-here
```

**Option C: Local Ollama (no API key needed)**

Install [Ollama](https://ollama.com/), pull a model (`ollama pull llama3`), and Sophia connects automatically on `localhost:11434`. No API key, no cloud, everything stays on your machine.

---

## Data Access

Sophia accesses TU Wien data through three tiers, each chosen for the data it can reliably reach:

1. **TUWEL AJAX API.** Session-cookie authenticated. TUWEL (TU Wien's Moodle instance) exposes a comprehensive AJAX API that powers its own web interface. Sophia uses this structured API for core data: enrolled courses, resources, activities, and forum posts. This is the most reliable data source.
2. **TISS Public API.** No authentication needed. TISS provides a public REST API for course metadata, exam dates, room information, and curricula. Sophia uses this to cross-reference course numbers and get official descriptions, ECTS credits, and exam schedules.
3. **HTML Scraping.** Session-cookie authenticated. Some data (grades, detailed assignment descriptions, embedded resource links) is only available in rendered HTML pages. Sophia parses these with BeautifulSoup as a last resort, with robust error handling for when page structures change.

**Privacy:** All data stays on your machine. Sophia communicates only with TU Wien servers you already use: TUWEL (`tuwel.tuwien.ac.at`) and TISS (`tiss.tuwien.ac.at`). No telemetry, no analytics, no third-party services. Your session cookie is stored locally in your platform's standard config directory and is never transmitted anywhere except back to TU Wien.

---

## Development

```bash
# Set up the development environment
uv sync --all-extras --group dev   # install all optional features + test/lint tools
uv run sophia lectures setup       # configure Hermes for your hardware (GPU, models, LLM provider)

# Or use the Makefile shortcuts:
# make dev                         # install deps
# make setup-hermes                # configure Hermes

# For users (no dev tools needed):
# uv sync                          # base install (core deps only)
# The lectures setup wizard auto-installs hermes deps when needed

# Run the test suite
uv run pytest                      # 908 tests currently passing
uv run pytest --cov=sophia     # with coverage report
uv run pytest -x               # stop on first failure (useful when debugging)

# Code quality
uv run ruff check .            # lint (style, complexity, imports)
uv run ruff format --check .   # check formatting
uv run pyright                 # strict type checking
```

The test suite uses `pytest` with `pytest-asyncio` for async tests, `respx` for HTTP mocking (no real network calls in tests), and `hypothesis` for property-based testing of domain models.

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make dev` | Install all extras + dev group |
| `make setup-hermes` | Configure Hermes hardware and providers |
| `make test` | Run tests with coverage (85% minimum) |
| `make lint` | Lint and format check |
| `make typecheck` | Type check with pyright |
| `make run` | Run sophia CLI |
| `make format` | Format code with ruff |
| `make clean` | Remove build artifacts (preserves .venv) |
| `make clean-all` | Remove everything including .venv |
| `make docker-build` | Build Docker image |
| `make docker-up` | Start services (detached) |
| `make docker-down` | Stop services |
| `make docker-logs` | Tail service logs |
| `make docker-backup` | Backup SQLite from Docker volume |

### Docker

```bash
docker compose build               # build image
docker compose up -d               # start (detached)
docker compose down                # stop
docker compose logs -f             # tail logs

# Backup database from container
make docker-backup                 # saves sophia-backup-YYYYMMDD.db
```

### CI/CD

GitLab CI runs on every push:

1. **Lint** — `ruff check` + `ruff format --check`
2. **Typecheck** — `pyright`
3. **Test** — `pytest` with coverage on Python 3.12 + 3.14 matrix (75% minimum coverage)
4. **Security** — `pip-audit` (allowed to fail)
5. **Docker build** — builds the image; pushes to GitLab Container Registry on `master` merges (tagged with commit SHA + `latest`)

CI runs automatically via GitLab CI on every push.

---

## Roadmap

| Status | Milestone | Description |
|--------|-----------|-------------|
| ✅ Done | **M0: MVP Foundation** | Authentication, TUWEL adapter, course listing, `sophia books discover` works against real TUWEL |
| ✅ Done | **Kairos: Registration** | TISS course & group registration with preference lists, watch mode for auto-submit |
| ✅ Done | **Kairos: Scheduler** | Cross-platform job scheduler (systemd/launchd/Task Scheduler) — `--schedule` and `sophia jobs` |
| ✅ Done | **Hermes: Lectures** | Lecture download, Whisper transcription (GPU/CPU), semantic search via embeddings |
| ✅ Done | **Hermes: Silence detection & management** | Auto-detect empty recordings via ffmpeg, `lectures process` E2E pipeline, discard/restore/purge management, knowledge base purge |
| ✅ Done | **Course Materials** | PDF scraping from TUWEL, ChromaDB indexing, lecture-material cross-linking |
| ✅ Done | **Athena: Study** | Topic extraction, confidence calibration, guided study sessions, flashcard review, self-explanation, Anki export |
| ✅ Done | **Athena: Pedagogical Depth** | Adaptive difficulty (cued/explain/transfer), FSRS-inspired spaced repetition, interleaved sessions, delayed feedback, no-skip pre-test |
| ✅ Done | **Security Hardening** | Command injection protection, SSRF whitelist, download size limits, non-root Docker, secret markers |
| ✅ Done | **CLI Refactor** | Modular CLI architecture with cyclopts, shared output formatting (JSON/table/quiet), module ID resolver |
| ✅ Done | **Reliability & Resilience** | Whisper timeout, SSO auth retry, embedder/knowledge store caching, subprocess timeouts |
| ✅ Done | **UX Polish** | Progress bars, status dashboard, quickstart command, Likert anchors |
| ✅ Done | **Docker & CI/CD** | Multi-stage Dockerfile, docker-compose, GitLab CI with lint/typecheck/test/security/docker-build |
| 🔨 In Progress | **M1: Bücherwurm Core** | ISBN resolution, Open Access + Anna's Archive search, download pipeline, usefulness prediction loop |
| 🔨 In Progress | **M2: Intelligence Layer** | PDF parsing with PyMuPDF, LLM-powered reference extraction (Gemini/Groq — LLM adapter already built in `topic_extractor.py`), Typst-rendered reading reports |
| 📋 Planned | **M3: Chronos** | Deadline import from TUWEL/TISS, effort estimation prompts, time tracking, reflection analytics |
| 📋 Planned | **M5: Polish & Ship** | Textual TUI, Gradio web interface, comprehensive documentation, stable public release |

---

## Quick Reference

Once you're set up, these are the commands you'll use most:

```bash
# Cross-Course Overview
uv run sophia status                       # dashboard: lectures, topics, cards, reviews due
uv run sophia quickstart <module-id>       # full pipeline in one command (skips completed steps)

# Authentication
uv run sophia auth login          # log in to TUWEL + TISS
uv run sophia auth status         # check if your session is valid
uv run sophia auth logout         # clear saved credentials

# Books (Bücherwurm)
uv run sophia books discover      # scan courses for textbook references

# Registration (Kairos)
uv run sophia register favorites           # list TISS favorites with registration info
uv run sophia register status 186.813      # check registration status
uv run sophia register groups 186.813      # show groups with schedule
uv run sophia register go 186.813          # register for LVA
uv run sophia register go 186.813 --preferences "1,3"   # with group preferences
uv run sophia register go 186.813 --watch  # wait for window, then register
uv run sophia register go 186.813 --preferences "1,3" --schedule  # install system timer

# Lectures (Hermes)
uv run sophia lectures setup               # configure hardware, models, providers
uv run sophia lectures list                # discover lecture recordings
uv run sophia lectures process <module-id>   # full pipeline: download → silence detection → transcribe → index → extract topics
uv run sophia lectures process <module-id> --materials  # include PDF indexing
uv run sophia lectures materials <course-id>   # scrape and list course materials (PDFs)
uv run sophia lectures status <module-id>    # per-episode status table (with skip reasons)
uv run sophia lectures download <module-id>  # download recordings (with silence detection)
uv run sophia lectures transcribe <module-id> # transcribe with Whisper
uv run sophia lectures index <module-id>   # build embedding index
uv run sophia lectures search "topic" <module-id>  # semantic search within a lecture
uv run sophia lectures discard <module-id> <episode-id>  # mark episode as discarded
uv run sophia lectures restore <module-id> <episode-id>  # undo discard
uv run sophia lectures purge <module-id> <episode-id>    # remove episode from knowledge base

# Study (Athena)
uv run sophia study topics <module-id>              # extract topics from transcripts
uv run sophia study confidence <module-id>          # rate confidence per topic
uv run sophia study session <module-id> [topic]     # guided study with pre/post test
uv run sophia study session <module-id> --interleave    # mix multiple topics
uv run sophia study session <module-id> --feedback-delay 45  # custom reflection time (seconds)
uv run sophia study review <module-id> [topic]      # review flashcards
uv run sophia study review <module-id> --interleave     # shuffle all topic cards
uv run sophia study review <module-id> --count 20       # review up to 20 cards
uv run sophia study explain <module-id> [topic]     # self-explain wrong answers
uv run sophia study explain <module-id> --count 10      # explain up to 10 cards
uv run sophia study export <module-id>              # export flashcards to Anki
uv run sophia study export <module-id> --blocked        # group by topic instead of interleaving
uv run sophia study due [module-id]                 # show topics due for review (all if omitted)

# Scheduled Jobs
uv run sophia jobs list            # show scheduled jobs
uv run sophia jobs cancel <job-id> # cancel a scheduled job

# Global Flags (available on all commands)
uv run sophia --json <command>     # output as JSON
uv run sophia --quiet <command>    # suppress output
uv run sophia --no-color <command> # disable colors
uv run sophia --debug <command>    # enable debug logging

# Help
uv run sophia --help               # show all commands
uv run sophia books --help         # show book subcommands
uv run sophia lectures --help      # show lecture subcommands
```

---

## Contributing

Sophia is a personal project, but contributions are welcome. If you're a TU Wien student and want to help:

1. Open an issue describing what you'd like to work on
2. Fork the repository and create a branch
3. Write tests for your changes
4. Submit a merge request

Please follow the existing code style (enforced by `ruff` and `pyright`). The codebase uses strict type checking, so if Pyright complains, that's a real issue, not noise.

---

## Acknowledgments

Sophia is named after the Greek word for wisdom (σοφία). The name reflects the project's aspiration: not to make students more efficient, but to help them become wiser. Better at knowing what they know, what they don't, and what to do about the gap.

---

> *"The only true wisdom is in knowing you know nothing." — Socrates*
>
> *Sophia doesn't just find the books. She helps you discover what you don't yet know.*
