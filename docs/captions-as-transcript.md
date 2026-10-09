# Captions as Transcript

Status: accepted 2026-10-09 — issue #156

## Context

Each Opencast episode's player page carries a Paella manifest
(`window.episode`) whose `captions` list names TU Wien's auto-generated
subtitle tracks: one WebVTT file per language on `cdn.video.tuwien.ac.at`,
labelled such as `"de Waas (Auto generated)"`. Until this change
`_parse_paella_tracks` read only `streams`, so Sophia downloaded the audio of
every lecture and ran Whisper over it.

Coverage, sampled on 2026-10-09:

| Module | Term | Episodes with captions |
|---|---|---|
| 2856855 (EP1) | winter 2025/26 | 38 of 39, German and English |
| 3022498 | summer 2026 | 1 of 3 sampled |
| 3022060 | this term | 0 of 3 sampled, so far |

What Whisper costs instead: on hephaestus's GTX 1070 (`int8`, #154), three
lectures took 51 min 47 s to transcribe, after their audio was downloaded.

## Predicted quality

The German track of the EP1 lecture of 2026-01-16 is 110 KB. Parsed by the
captions adapter it yields 1,313 timed cues and 10,756 words, which is the
figure the issue estimated by eye. It is fluent and punctuated and gets the
technical terms right — "generisch", "Compiler", "Strings", "Index-Zugriff" —
which puts it on a par with local Whisper `large-v3`.

The prediction this record makes, and that the migration below rests on: a
transcript read from these captions serves topic extraction, indexing and
grounded questions at least as well as a Whisper transcript of the same
lecture, at no GPU cost and no download. That is a prediction from one read
sample, not a measurement. If it turns out wrong for some course, the
`source` column is what lets a later comparison tell the two apart.

The English track is a machine translation of the German one and is not
used as study material unless the course's configured language is English,
in which case the track choice below picks it.

## Decision

Captions first, Whisper only for a lecture that has none.

- **Order.** `transcribe_from_captions` is the first pipeline stage, before
  the download stage. For every episode whose manifest offers a usable track
  it fetches the WebVTT, stores the cues as transcript segments with their
  times, and records the row. The download stage then skips every episode
  that already has a completed transcript, so a captioned lecture costs
  neither the audio nor Whisper.
- **Which track.** The track in the course's configured language, falling
  back to German. The course's language is the learning path's exam
  language, read through the module's discovered course; a module with no
  known course reads German. Detecting the spoken language from an audio
  sample was rejected because it needs a download per episode, which is the
  cost captions exist to avoid. The per-course transcription language #128
  plans replaces the exam-language lookup when it exists. (Fork answered by
  the user on 2026-10-09; recorded in commit `ef3f37c`.)
- **Fallback.** An episode with no track in either language, or whose file
  cannot be fetched, is not WebVTT, or has no cues, is left for Whisper. One
  log line per episode names the source taken (`transcript_source`) and,
  on fallback, the reason (`captions_fallback`, a warning; `captions_unavailable`
  when no track qualifies). Nothing is written for a fallen-back episode, and
  the rest of the run continues. The fallback is never silent.
- **Same shape.** A caption transcript lives in `transcriptions` and
  `transcript_segments` exactly as a Whisper one does, so indexing, topic
  extraction, search and grounded questions read it unchanged. No file is
  written for it; the caption URL is its provenance.

## The schema change (migration 0004)

`transcriptions` gains three columns and loses a constraint:

| Change | Why |
|---|---|
| `source` text, `captions` or `whisper`, default `whisper` | Records where the text came from; `sophia lectures status` shows it. Existing rows are Whisper's. |
| `title` text, default `""` | A caption transcript is the only record of its episode. Whisper rows now carry it too. |
| `caption_url` text, nullable | Which published file was read. |
| drop `fk_transcriptions_episode_id_lecture_downloads` | A caption transcript has no download behind it and must not carry a fake download row to satisfy a foreign key. |

The downgrade has to restore the foreign key, and caption transcripts cannot
satisfy it, so it deletes transcriptions without a download row — with their
segments and index entries — before re-adding the constraint. That is written
in the migration rather than hidden.

### Consequences for readers

`lecture_downloads` was the episode catalogue for as long as every transcript
came from a download. Readers that listed a module's episodes from it alone
now go through `services/hermes_episodes.py`, which joins both tables fully:
the indexer's title lookup, the search scope, topic grounding and its
provenance titles, the pipeline status, purge, the episode count and the
module catalogue. The status row of an episode that was never downloaded
reports `download_status` `none`, which the CLI renders as a dash, and the
content page counts an item ready when it is transcribed and indexed, whether
or not it was downloaded.

Three things stay on the download row and so do not apply to a captioned
lecture: `lecture_number` (the status table's `#` column is empty for it),
`missed_at` (it cannot be marked missed) and `discard` (it cannot be
discarded, though a lecture discarded before its captions were read stays
excluded). Worse, `assign_lecture_numbers` numbers only the downloaded
lectures, so in a mixed module the one Whisper lecture is numbered as if the
captioned ones did not exist: on EP1 the sixteenth lecture reads `#1`. All of
it wants a home that both kinds of transcript share; that is a follow-up, not
part of this change.

## Verifying it on the real stack

`sophia lectures process <module>` runs the whole pipeline. Two things to know
before walking it:

- Topics are keyed by module id (`extract_topics_from_lectures` sets
  `course_id = module_id`), while the learning-path picker offers TUWEL course
  ids, so `/app/topics` lists a module's topics only when the session's
  learning path *is* that module id. `scripts/mint_session.py
  --learning-path-id <module id>` is the documented way to start a walk there;
  the id-space mismatch is #103's.
- On hephaestus Whisper runs on the GPU as `int8` (#154) while the installed
  PyTorch has no kernels for that GPU, so the embedding stage has to run on
  the CPU. Running the pipeline as one command needs the GPU for Whisper and
  the CPU for embeddings in the same process; until the per-stage pipeline
  fixes land, running `transcribe` and `index` as separate commands is the
  way that works on that box.

## Out of scope

- Re-transcribing lectures that Whisper already did once captions appear
  later.
- Using the English captions as study material.
- Editing or correcting captions.
