# Sophia (Σοφία)

*"I am the love of wisdom, the spirit that kindles the flame of truth in those who seek it."*

A student toolkit for TU Wien that automates the tedious parts of academic life (finding+ aquiring textbooks, tracking deadlines, analyzing exams) so you can focus on what matters: understanding.

**Status:** Early development (v0.1.0). Bücherwurm (book discovery) is functional, Kairos (registration with scheduler) and Hermes (lecture knowledge base) are functional. Bücherwurm download/library features are in progress. Chronos and Athena are planned.

| Section | What's There |
|---------|-------------|
| [Getting Started](#getting-started) | Step-by-step setup from zero to running |
| [What Sophia Does](#what-sophia-does) | The three modules and what each one handles |
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

## Getting Started

This section is written for you if you've never opened a terminal, cloned a repository, or installed a developer tool. Every step is explained from scratch, no prior knowledge assumed. You'll be up and running in about ten minutes.

> 💡 If you already know your way around a terminal, skip to [Step 6](#step-6-log-in-to-tuwel). You just need `uv sync` and `uv run sophia auth login`.

### Step 1: Open a Terminal

A terminal (also called a command line, console, or shell) is a text-based interface to your computer. Instead of clicking buttons in a graphical window, you type short commands and press Enter. It sounds old-fashioned, but it's by far the fastest way to install and run developer tools, and once you get the hang of it you'll wonder how you lived without it.

You'll only need a handful of commands for Sophia. Here's how to open a terminal on your system:

- **Windows 10/11:** Press `Win + R`, type `wt`, and press Enter to open Windows Terminal. If that doesn't work, search for "PowerShell" in the Start menu and open it. Either one works.
- **macOS:** Press `Cmd + Space` to open Spotlight, type "Terminal", and press Enter.
- **Linux:** Press `Ctrl + Alt + T` on most distributions, or find "Terminal" in your application menu.

✅ You should see a window with a blinking cursor waiting for input. That's your terminal. Don't close it; you'll use it for the next steps.

### Step 2: Install Python 3.12+

Sophia requires Python 3.12 or newer. Check if you already have it by typing this into your terminal and pressing Enter:

```bash
python3 --version
```

On Windows, you may need to use `python` instead of `python3`:

```powershell
python --version
```

If you see `Python 3.12.x` or higher, you're set. Skip to the next step. If the version is older, or if you get a "command not found" error, download Python from [python.org/downloads](https://www.python.org/downloads/) and install it.

> 💡 **Windows users:** During installation, there's a checkbox at the bottom of the first screen that says **"Add Python to PATH"**. Check it. If you miss this, Python won't be available in your terminal and you'll have to reinstall.

✅ `python3 --version` (or `python --version`) prints 3.12 or higher.

### Step 3: Install uv (the Package Manager)

uv is a fast Python package manager. Think of it as an app store for Python projects that downloads everything Sophia needs to run.

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing, **close and reopen your terminal** so the `uv` command becomes available.

✅ `uv --version` prints a version number.

### Step 4: Clone the Repository

"Cloning" means downloading a copy of the project's source code to your computer. It's the standard way to get code from a repository like GitLab.

First, make sure you have Git installed:

```bash
git --version
```

If you get an error, install Git from [git-scm.com/downloads](https://git-scm.com/downloads). On Windows, the installer has many options, but the defaults are fine. Just click through.

Once Git is ready, run this command to download Sophia:

```bash
git clone https://gitlab.com/mipkovich/sophia.git && cd sophia
```

This does two things: `git clone` downloads the project into a new folder called `sophia`, and `cd sophia` moves your terminal into that folder.

> 💡 The `&&` between commands means "run the second command only if the first one succeeded." You'll see this pattern a lot in terminal instructions.

✅ You're now inside the `sophia` directory. You can verify by typing `pwd` (Linux/macOS) or `cd` (Windows). It should end with `/sophia`.

### Step 5: Install Sophia

```bash
uv sync
```

This reads the project's dependency list and installs everything Sophia needs into a local virtual environment. Think of it as installing an app. You only do this once (and again after updates). The virtual environment means nothing is installed globally on your system; everything stays neatly inside the project folder.

> 💡 If you see a message about creating a `.venv`, that's normal. It's the virtual environment where Sophia's dependencies live.

✅ You see output ending with something like "Resolved ... packages" or "Audited ... packages".

### Step 6: Log in to TUWEL

```bash
uv run sophia auth login
```

You'll be prompted for your TU Wien credentials, the same username and password you use for TUWEL and TISS. Sophia saves a session cookie on your machine so it can access TUWEL on your behalf. Nothing is sent anywhere except to TU Wien's own servers.

✅ You see a success message with your name.

### Step 7: Discover Books

```bash
uv run sophia books discover
```

Sophia scans your enrolled TUWEL courses, extracts textbook references from course descriptions and resources, and prints a table of everything it found. The output looks something like this:

```
                        Discovered Book References
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Title                       ┃ Author(s)     ┃ ISBN           ┃ Source   ┃ Course                     ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Introduction to Algorithms  │ Cormen et al. │ 978-0-262-046… │ syllabus │ Algorithms & Data Struc.   │
│ Algorithm Design            │ Kleinberg, T. │ 978-0-321-295… │ resource │ Algorithms & Data Struc.   │
│ Principles of Math. Anal.   │ Rudin, W.     │ 978-0-07-054…  │ syllabus │ Analysis 1                 │
└─────────────────────────────┴───────────────┴────────────────┴──────────┴────────────────────────────┘
```

✅ A table of textbook references appears. You're done. Welcome to Sophia.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `command not found` after installing uv | Close your terminal and open a new one. The install script updated your PATH, but the current terminal doesn't know yet. |
| Python version is too old | Install Python 3.12+ from [python.org](https://www.python.org/downloads/). On Linux, you may need `sudo apt install python3.12`. |
| Login fails | Double-check your credentials. If it still fails, try `uv run sophia auth login --debug` for more details. |
| `git` not found | Install Git from [git-scm.com/downloads](https://git-scm.com/downloads), then restart your terminal. |
| `sophia lectures setup` is slow | The first run downloads large models (Whisper, sentence-transformers, CUDA libraries). This is normal and only happens once. Expect 1–5 GB depending on model size. |
| GPU not detected during Hermes setup | Ensure NVIDIA drivers are installed (`nvidia-smi` should show your GPU). On WSL, you need WSL2 with GPU passthrough enabled. The setup wizard falls back to CPU mode if no GPU is found. |

---

## What Sophia Does

Sophia is organized into modules, each named for a concept that matches its purpose:

| Module | Command | What It Does | Status |
|--------|---------|--------------|--------|
| **Bücherwurm** 📚 | `sophia books` | Discovers textbook references from enrolled TUWEL courses (ISBN extraction, metadata enrichment) | ✅ Discovery |
| **Kairos** ⚡ | `sophia register` | Automates TISS course and group registration with preference lists — seize the right moment | ✅ Functional |
| **Hermes** 🎙️ | `sophia lectures` | Lecture knowledge base: download recordings, transcribe with Whisper, semantic search | ✅ Functional |
| **Chronos** ⏰ | `sophia deadlines` | Deadline coach that helps you estimate effort, prioritize tasks, and reflect on what worked | 📋 Planned |
| **Athena** 🎓 | `sophia study` | Study companion: topic extraction, confidence calibration, guided sessions, spaced review | ✅ Functional |

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
3. **`sophia lectures download <module-id>`** — download recordings (prefers audio for efficiency)
4. **`sophia lectures transcribe <module-id>`** — transcribe with Whisper, VAD filtering, hallucination detection
5. **`sophia lectures index <module-id>`** — chunk transcripts and build embedding index
6. **`sophia lectures search "topic" <module-id>`** — semantic search within a lecture's transcripts

Step 1 only needs to happen once. The setup wizard detects your GPU, recommends a Whisper model based on VRAM, lets you choose an LLM provider (GitHub Models, Gemini, Groq, or Ollama), and automatically installs the heavy dependencies (`faster-whisper`, `chromadb`, `sentence-transformers`) when needed.

### What's Coming: Chronos and Athena

**Chronos** will pull assignment deadlines from TUWEL and TISS, but it won't just list them in a calendar. TUWEL already does that, and students still miss deadlines. The problem isn't information, it's planning. Chronos asks you to estimate how long each task will take *before* you start, tracks your actual time, and helps you see where your estimates fall short. Over a semester, you develop better planning intuition, a skill that transfers far beyond university.

**Athena** is now functional! It extracts topics from lecture transcripts, asks you to rate your confidence per topic, then runs guided study sessions with pre/post testing to measure actual learning. Flashcards are generated during study and reviewed with spaced repetition. Self-explanation exercises with fading scaffolds deepen understanding. Export to Anki for mobile review.

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
├── domain/           # Pure models, protocols, domain events
│   ├── models.py     # Book, Course, Deadline, ExamTopic, etc.
│   ├── ports.py      # Protocol definitions (CourseProvider, BookSearcher, ...)
│   ├── events.py     # Domain events (BookDiscovered, DeadlineApproaching, ...)
│   └── errors.py     # Domain-specific error hierarchy
├── services/         # Orchestration and business logic
│   ├── pipeline.py   # Book discovery pipeline
│   ├── reference_extractor.py
│   ├── resource_classifier.py
│   ├── registration.py        # Kairos preference-based registration
│   ├── job_runner.py          # Cross-platform job scheduler (systemd/launchd/Task Scheduler)
│   ├── hermes_setup.py        # Hardware detection, config wizard
│   ├── hermes_download.py     # Lecture download with audio extraction
│   ├── hermes_transcribe.py   # Whisper transcription with VAD and hallucination filtering
│   └── hermes_index.py        # Chunking, embeddings, semantic search orchestration
├── adapters/         # External world implementations
│   ├── moodle.py     # TUWEL/Moodle AJAX adapter
│   ├── tiss.py       # TISS public API adapter
│   ├── tiss_registration.py   # TISS registration (JSF scraping)
│   ├── auth.py                # SSO authentication flow
│   ├── lecturetube.py         # TUWEL Opencast lecture discovery
│   ├── lecture_downloader.py  # Recording download adapter
│   ├── transcriber.py         # Whisper adapter (faster-whisper)
│   ├── embedder.py            # Embedding adapter (sentence-transformers)
│   └── knowledge_store.py     # Vector store adapter (ChromaDB)
├── infra/            # Cross-cutting concerns
│   ├── http.py       # Shared HTTP client with retry logic
│   ├── persistence.py # SQLite via aiosqlite
│   ├── di.py         # Dependency injection container
│   └── logging.py    # Structured logging (structlog)
└── ui/               # User interfaces (future)
    ├── tui/          # Terminal UI via Textual
    └── web/          # Web UI via Gradio
```

Key design decisions:

- **Protocol-based dependency injection.** Services depend on protocols (`typing.Protocol`), not concrete implementations. The DI container wires adapters to protocols at startup. This makes the system both testable (swap in mocks) and extensible (add new adapters without touching services).
- **Domain events.** State changes emit events (`BookDiscovered`, `ReferenceExtracted`, etc.) that other components can react to, keeping modules decoupled and enabling future features like activity logging.
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
| openai | Connects to GitHub Models or local Ollama for topic extraction | Optional | `uv sync --extra llm` |
| faster-whisper | Transcribes lecture recordings (speech-to-text) | Optional | `uv sync --extra hermes` |
| sentence-transformers | Encodes text into vectors for semantic search over lectures | Optional | `uv sync --extra hermes` |
| chromadb | Stores and searches lecture embeddings (vector database) | Optional | `uv sync --extra hermes` |
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
| openai (≥ 1.50) | GitHub Models / Ollama | — | [GitHub PAT](https://github.com/settings/tokens) (for GitHub Models) |

**Which one should I pick?**

- **Gemini** — generous free tier, good quality. Best default choice.
- **Groq** — extremely fast inference, free tier available. Good if you value speed.
- **Ollama** (via the openai package) — runs entirely on your machine, no API key needed, no data leaves your computer. Requires [Ollama](https://ollama.com/) installed separately. Best for privacy-conscious users or offline use.

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
uv run pytest                      # 420 tests currently passing
uv run pytest --cov=sophia     # with coverage report
uv run pytest -x               # stop on first failure (useful when debugging)

# Code quality
uv run ruff check .            # lint (style, complexity, imports)
uv run ruff format --check .   # check formatting
uv run pyright                 # strict type checking
```

The test suite uses `pytest` with `pytest-asyncio` for async tests, `respx` for HTTP mocking (no real network calls in tests), and `hypothesis` for property-based testing of domain models.

See the `Makefile` for additional convenience targets (`make test`, `make lint`, `make typecheck`). CI runs automatically via GitLab CI on every push.

---

## Roadmap

| Status | Milestone | Description |
|--------|-----------|-------------|
| ✅ Done | **M0: MVP Foundation** | Authentication, TUWEL adapter, course listing, `sophia books discover` works against real TUWEL |
| ✅ Done | **Kairos: Registration** | TISS course & group registration with preference lists, watch mode for auto-submit |
| ✅ Done | **Kairos: Scheduler** | Cross-platform job scheduler (systemd/launchd/Task Scheduler) — `--schedule` and `sophia jobs` |
| ✅ Done | **Hermes: Lectures** | Lecture download, Whisper transcription (GPU/CPU), semantic search via embeddings |
| 🔨 In Progress | **M1: Bücherwurm Core** | ISBN resolution, Open Access + Anna's Archive search, download pipeline, usefulness prediction loop |
| 📋 Planned | **M2: Intelligence Layer** | PDF parsing with PyMuPDF, LLM-powered reference extraction (Gemini/Groq), Typst-rendered reading reports |
| 📋 Planned | **M3: Chronos** | Deadline import from TUWEL/TISS, effort estimation prompts, time tracking, reflection analytics |
| ✅ Done | **Athena: Study** | Topic extraction, confidence calibration, guided study sessions, flashcard review, self-explanation, Anki export |
| 📋 Planned | **M5: Polish & Ship** | Textual TUI, Gradio web interface, comprehensive documentation, stable public release |

---

## Quick Reference

Once you're set up, these are the commands you'll use most:

```bash
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
uv run sophia lectures download <module-id>  # download recordings
uv run sophia lectures transcribe <module-id> # transcribe with Whisper
uv run sophia lectures index <module-id>   # build embedding index
uv run sophia lectures search "topic" <module-id>  # semantic search within a lecture

# Study (Athena)
uv run sophia study topics <module-id>              # extract topics from transcripts
uv run sophia study confidence <module-id>          # rate confidence per topic
uv run sophia study session <module-id> [topic]     # guided study with pre/post test
uv run sophia study review <module-id> [topic]      # review flashcards
uv run sophia study explain <module-id> [topic]     # self-explain wrong answers
uv run sophia study export <module-id>              # export flashcards to Anki
uv run sophia study due                             # show topics due for review

# Scheduled Jobs
uv run sophia jobs list            # show scheduled jobs
uv run sophia jobs cancel <job-id> # cancel a scheduled job

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
