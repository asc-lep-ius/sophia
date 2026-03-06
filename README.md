# Sophia (Σοφία)

*"I am the love of wisdom, the spirit that kindles the flame of truth in those who seek it."*

A student toolkit for TU Wien that automates the tedious parts of academic life (finding textbooks, tracking deadlines, analyzing exams) so you can focus on what matters: understanding.

**Status:** Early development (v0.1.0). Bücherwurm (book discovery) is functional. Chronos and Athena are planned.

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
┌──────────────────────────────────────────────────────────────────────────────┐
│  Bücherwurm — Discovered References                                         │
├─────────────────────────┬──────────────────────────────┬─────────────────────┤
│ Course                   │ Title                         │ ISBN                │
├─────────────────────────┼──────────────────────────────┼─────────────────────┤
│ Algorithms & Data Struc. │ Introduction to Algorithms     │ 978-0-262-04630-5   │
│ Algorithms & Data Struc. │ Algorithm Design               │ 978-0-321-29535-4   │
│ Analysis 1               │ Principles of Math. Analysis   │ 978-0-07-054235-8   │
└─────────────────────────┴──────────────────────────────┴─────────────────────┘
 Found 12 references across 5 courses.
```

✅ A table of textbook references appears. You're done. Welcome to Sophia.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `command not found` after installing uv | Close your terminal and open a new one. The install script updated your PATH, but the current terminal doesn't know yet. |
| Python version is too old | Install Python 3.12+ from [python.org](https://www.python.org/downloads/). On Linux, you may need `sudo apt install python3.12`. |
| Login fails | Double-check your credentials. If it still fails, try `uv run sophia auth login --debug` for more details. |
| `git` not found | Install Git from [git-scm.com/downloads](https://git-scm.com/downloads), then restart your terminal. |

---

## What Sophia Does

Sophia is organized into three modules, each named for a concept that matches its purpose:

| Module | Command | What It Does | Status |
|--------|---------|--------------|--------|
| **Bücherwurm** 📚 | `sophia books` | Finds textbook references in your courses, searches Open Access libraries and Anna's Archive, downloads them | ✅ Functional |
| **Chronos** ⏰ | `sophia deadlines` | Deadline coach that helps you estimate effort, prioritize tasks, and reflect on what worked | 📋 Planned |
| **Athena** 🎓 | `sophia exams` | Analyzes past exams for topic patterns, builds flashcards, calibrates your confidence | 📋 Planned |

### Bücherwurm in Action

Bücherwurm (German for "bookworm") scans your enrolled TUWEL courses and extracts every textbook reference it can find, from course descriptions, uploaded syllabi, resource sections, and forum posts. It then:

1. Resolves ISBNs and enriches metadata (title, authors, edition, publisher)
2. Searches Open Access repositories and Anna's Archive for available copies
3. Presents you with a clean table of results, grouped by course
4. Lets you download books directly to a local library organized by semester

Before downloading, Sophia asks you to predict whether each book will actually be useful for your studies. After a few weeks, it asks you to revisit that prediction. This builds your ability to evaluate resources before committing time to them.

### What's Coming: Chronos and Athena

**Chronos** will pull assignment deadlines from TUWEL and TISS, but it won't just list them in a calendar. TUWEL already does that, and students still miss deadlines. The problem isn't information, it's planning. Chronos asks you to estimate how long each task will take *before* you start, tracks your actual time, and helps you see where your estimates fall short. Over a semester, you develop better planning intuition, a skill that transfers far beyond university.

**Athena** will analyze past exam papers to surface recurring topic patterns and question styles. But instead of handing you a study guide, it asks you to predict which topics will appear and how confident you are about each one, then shows you the historical data. It generates flashcard *prompts* (not answers; you write those) and tracks your confidence calibration across topics. The goal is to make your preparation more strategic and less anxious.

---

## Philosophy: Why Sophia Doesn't Just Do Everything for You

It would be easy to build a tool that auto-generates study plans, pre-makes flashcards, and tells students exactly what to do. Many edtech products do precisely this, optimizing for the feeling of productivity rather than actual learning. Sophia deliberately does none of these things. The reason has to do with how learning actually works, and decades of cognitive science research point in the same direction.

### The Constructivist Foundation

Sophia is built on Jean Piaget's constructivist epistemology: the idea that knowledge is not passively received but actively constructed through experience. A student who reads a summary is not doing the same cognitive work as a student who wrestles with the material and builds their own understanding. The summary might transmit information, but information is not knowledge. Knowledge requires the learner to integrate new ideas with existing schemas, to assimilate where possible and accommodate where necessary.

This has real design consequences. Every feature passes through a filter: *does this help the student construct understanding, or does it bypass thinking?* If a feature does the thinking for you, it doesn't ship.

> *"The principal goal of education in the schools should be creating men and women who are capable of doing new things, not simply repeating what other generations have done."*
> — Piaget, in Bringuier, *Conversations with Jean Piaget* (1980), p. 132

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

- **Piaget:** Constructivism and equilibration: knowledge is built through prediction, conflict, and accommodation. This gives Sophia its core loop: predict → act → reflect.
- **Vygotsky:** Zone of proximal development: effective tools scaffold what's currently too hard and fade support as competence grows. Sophia's prompts become less frequent as your calibration improves.
- **Bjork & Bjork** (1992): Desirable difficulties: conditions that make learning harder in the short term (spacing, interleaving, retrieval practice) enhance long-term retention and transfer. Sophia never optimizes for short-term ease.
- **Kapur** (2008): Productive failure: students who struggle with a problem before receiving instruction develop deeper conceptual understanding than those given instruction first. Sophia lets you struggle with predictions before showing data.
- **Dunlosky et al.** (2013): Comprehensive review of learning strategies. Self-explanation and practice testing ranked as the highest-utility strategies. Sophia emphasizes both.
- **Roediger & Karpicke** (2006): The testing effect: retrieving information from memory strengthens retention more than re-reading it. Athena's flashcard system is built entirely on retrieval practice.

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
│   └── resource_classifier.py
├── adapters/         # External world implementations
│   ├── moodle.py     # TUWEL/Moodle AJAX adapter
│   ├── tiss.py       # TISS public API adapter
│   └── auth.py       # SSO authentication flow
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
uv sync --all-extras          # install everything including dev & optional tools

# Run the test suite
uv run pytest                  # 210 tests currently passing
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
| 🔨 In Progress | **M1: Bücherwurm Core** | ISBN resolution, Open Access + Anna's Archive search, download pipeline, usefulness prediction loop |
| 📋 Planned | **M2: Intelligence Layer** | PDF parsing with PyMuPDF, LLM-powered reference extraction (Gemini/Groq), Typst-rendered reading reports |
| 📋 Planned | **M3: Chronos** | Deadline import from TUWEL/TISS, effort estimation prompts, time tracking, reflection analytics |
| 📋 Planned | **M4: Athena** | Past exam scraping, topic frequency analysis, flashcard prompt generation, spaced repetition scheduling, confidence calibration |
| 📋 Planned | **M5: Polish & Ship** | Textual TUI, Gradio web interface, comprehensive documentation, stable public release |

---

## Quick Reference

Once you're set up, these are the commands you'll use most:

```bash
# Authentication
uv run sophia auth login          # log in to TUWEL
uv run sophia auth status          # check if your session is valid
uv run sophia auth logout          # clear saved credentials

# Books (Bücherwurm)
uv run sophia books discover       # scan courses for textbook references
uv run sophia books list           # show previously discovered books
uv run sophia books search <query> # search for a specific book

# Coming soon
uv run sophia deadlines            # (Chronos — planned)
uv run sophia exams                # (Athena — planned)

# Help
uv run sophia --help               # show all commands
uv run sophia books --help         # show book subcommands
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
