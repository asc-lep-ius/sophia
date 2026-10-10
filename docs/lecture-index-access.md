# How the API Reads the Lecture Index

Status: accepted 2026-10-10 — issue #129

## Context

Grounded study questions and lecture search both start the same way: embed a
short text (the topic, or the phrase the student typed) and look its nearest
transcript chunks up in the ChromaDB index under `$SOPHIA_DATA_DIR/knowledge`.
The processing worker (#128) builds that index; the API only reads it.

Until this change the API could not read it anywhere:

- **The API image** had neither `chromadb` nor `sentence-transformers`, so every
  query raised `EmbeddingError("chromadb not installed …")`.
- **The run contract on hephaestus** runs the API from the host venv, which has
  both, but sentence-transformers picks a CUDA device whenever PyTorch sees one.
  PyTorch 2.10 has no kernels for the GTX 1070 (sm_61), so every query raised
  `EmbeddingError: CUDA error: no kernel image is available`. Study
  (`study_questions.py` caught only `TopicExtractionError`) and search both
  answered 500, and every deck was empty (#130, #131).
- **A long-running API never saw new lectures.** chromadb loads a collection's
  vectors once per process and does not read back what another process wrote.
  Measured with chromadb 1.5.5: after a second process added a chunk, the
  reader's `count()` went up and its queries still missed the chunk, even
  through a fresh client on the same path. An API that had answered one query
  before the worker indexed a lecture would never ground anything in it.

## Options

1. **Embed in the API, on the CPU.** Install chromadb and sentence-transformers
   in the API image with PyTorch's CPU build, and embed each query in the API
   process.
2. **Route queries to the worker.** The API sends the text, the worker embeds
   it and searches, and the answer comes back.

## Decision

Fork: how the API reads the lecture index. Taken: embed queries in the API process on the CPU, with chromadb and a CPU-only PyTorch in the API image, using the `[embeddings]` model the index was built with. Rejected: route queries to the worker. Why: it predicts an API image of 2.01 GB instead of 452 MB, a query embedded in ~0.05 s after a 5–8 s model load on a process's first query, ~2 GB more resident per API process and no GPU ever touched, while routing would make every study session and search depend on a worker that has no request channel and is not yet deployed in production.

The second option needs a request/response channel the worker does not have —
it polls Postgres for jobs every 5 s and runs its stages in child processes so
that its own process never loads a model. Production runs the worker behind a
compose profile until CI publishes its image, so grounded study would not exist
there at all. And a worker busy with a 16-minute Whisper run would have to
answer queries beside it.

## What it predicts

Measured on hephaestus on 2026-10-10 against the EP1 2026W index (5 lectures,
6,462 chunks, `intfloat/multilingual-e5-large`, 16 cores), in the image this
change builds:

- **Image size.** The API image grows from 452 MB to 2.01 GB. The CUDA build of
  PyTorch would have made it ~10 GB: the worker image, which carries it, is
  13.4 GB. The Dockerfile skips every `nvidia-*`, `cuda-*` and `triton` wheel
  and installs `torch==<locked version>+cpu` from PyTorch's CPU index, reading
  both the list and the version from `uv.lock`.
- **Query latency.** The first query in an API process loads the model: 5–8 s
  from the local Hugging Face cache, plus a ~2.2 GB download on a host that has
  never fetched it (`HF_HOME` is on the data volume, shared with the worker).
  After that, embedding a query takes ~0.05–0.07 s and the search ~0.1 s; the
  first search of a process also opens the index (~0.6 s here).
- **CPU embedding behaviour.** The API process grows by ~2 GB resident once
  the model is loaded, and keeps it for its lifetime: one model per process
  (`hermes_index.query_embedder`). A query briefly uses the CPU's cores; the GPU
  is never touched, so the API needs none and cannot fail the way the GTX 1070
  made it fail. CPU and GPU embeddings of the same model differ only by float
  rounding, which does not change a ranking.
- **Same model on both sides.** The query embedder and the indexer read
  `[embeddings] model` from the same `hermes.toml`: the run contract mounts the
  host's config directory into the worker at the same path, and production
  mounts `sophia-config` at `/config` in both containers. A model of another
  dimension is refused by chromadb, which the API reports as
  `lecture_index.unavailable`. A model of the *same* dimension is not
  detectable and ranks badly, so changing the model means indexing every
  lecture again.
- **Freshness.** The store compares the index files' modification stamps on
  every call and reopens the index when another process has written to it
  since. A read changes neither stamp, so the check costs a `stat` and the
  reopen happens once per worker write.

## When the index cannot be read

Study falls back to the template question and the card says why
(`fallback_reason: index_unavailable`, recorded as the provenance generator
`fallback-template:index-unavailable` so a reload keeps the reason). Search
answers `503 lecture_index.unavailable` and the page says so in words. Neither
is a 500.
