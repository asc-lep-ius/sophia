# Perspectives

The seats `/council` may convene on a fork in this project. Every `##` heading in
this file is a seat and nothing else is — `convene.sh` checks each seat name
against those headings, so a seat nobody wrote down is refused rather than quietly
counted, and a heading here that is not a seat would be offered as one.

**The seats below the `---` are this project's own.** The three this file ships
with are an example: none is a default, none is privileged, and every one of them
is meant to be replaced. `/project-setup` derives a project's seats from what it
detected and asks before writing them, and the paragraph below the line keeps
saying so — until it is deleted along with the seats it describes.

**A perspective earns a seat only if both are true**: its loss function conflicts
with another seat's *on this fork*, and it bears a cost if the decision is wrong.
Derive the seats from the blast radius — who implements and pays, who owns the
domain's ontology, who holds a veto — and ground each one in something named: the
artefact it reads, the measurement it is judged on, the incident it remembers.

A title is not grounding, and that is measured rather than asserted. Role labels
bought no accuracy across 162 personas and 2,410 questions (Zheng et al., EMNLP
Findings 2024), and an expert persona costs accuracy on retrieval and strict
reasoning even where it buys alignment — MMLU 68.0% against a 71.6% baseline with
no persona at all (arXiv 2603.18507). What a seat is worth is the cost it carries,
so write the cost down and the label stops mattering.

**Cap a council at three — the registry itself is not capped.** Two seats that
would score every option alike are one seat, and `convene.sh` says so in the
render when it sees it. Three seats are also not three votes — one model wearing
three system prompts is correlated judging at its worst, and nine judges drawn
from seven model families measured about two effective votes (arXiv 2605.29800),
which is why the output is the objections and not the agreement.

**Deriving them for this project.** Read what the project actually has, and give a
seat only to a cost that is really borne here. A library with no runnable surface
has no operator at 5am; a repo with no public route has nobody paying for a broken
contract.

| What this project has | Who pays, and therefore might earn a seat |
|---|---|
| A runnable surface — `RUN_CMD` set, a server, a daemon | whoever reads the ledger at 5am and decides whether to intervene |
| A published route, slug, format or API other people call | whoever answers for a contract that cannot be taken back |
| Real users, or copy that tells them something | whoever owns what a word in this product means |
| A double on a user flow with no `PARITY_CMD` pinning it | whoever finds out in production that the tests tested the double |
| Data that outlives a release — migrations, a ledger, an audit trail | whoever has to reconstruct what was known at the time |
| CI that gates other people's merges | whoever is blocked when the pipeline is red for a reason nobody can read |
| A regulated or money-touching path | whoever signs off, and can stop a release |
| None of the above — a library, a CLI, a template repo | the implementer and the reader, and that may genuinely be all there is |

Two or three seats is where a project starts. Reaching for one more that would
score everything the way an existing seat does makes the render say so; the
registry grows instead by promotion, one fork at a time, as below.

**A seat promoted for one fork.** Some forks have a payer the standing seats do
not cover. `/council` may promote **at most one** seat for a fork, and the rules
are structural rather than advisory:

- **It is written into this file before any seat is dispatched**, never once the
  scores are back. `convene.sh` refuses a seat that heads no block here, so a seat
  invented mid-convening is already a refusal — but the ordering is the part that
  matters, because a seat chosen after the answer is known is a seat chosen to
  reach it.
- **It carries a `**Promoted.**` line** naming the date and the fork verbatim, as
  the first line of its block. `convene.sh` reads that line: two seats promoted
  for the same fork is a refusal, and the render names the promoted seat so a
  reader can discount its score against the standing seats'.
- **It stays.** A seat promoted in March is a standing seat in April — it now
  predates the fork it is scoring, which is the whole point — and this file is in
  git, so `git log -p` shows when the roster changed and against which fork.
- **If three standing seats already bear this fork's cost**, that is the answer:
  the fork does not get a fourth voice, because a council seats three. Convene
  with those three, and say in the block which cost went unrepresented. A
  registry of six seats is not too many; a council of four is.

Indented here so it is not itself a heading, but write it at the left margin:

    ## the tenant's accountant
    **Promoted.** 2026-09-18, for the fork: which locale governs the invoice number sequence?
    **Loss function.** ...

**Never a demographic seat** — age, gender, nationality, class. Generated personas
drift stereotypical when nothing stops them (arXiv 2605.05682), and gender-neutral
roles measured better than gendered ones (Zheng et al.). A seat is a loss
function, not a person.

**Never a seat chosen after you know what you want.** The registry exists so that
the roster predates the fork. Picking the critics once there is a preferred option
is the casting version of self-preference bias, which is measured well enough in
LLM judging to assume here (arXiv 2404.13076).

**Never a seat that agrees with you.** A seat with no objection is a seat that was
not needed, which is why the schema demands a `strongest_con` from every seat.

**Never convene** for a trivial fork; for a fork a cheap measurement answers — run
the measurement; or for a fork the decision boundary already owns, in either
direction.

---

## the student before the exam

**Loss function.** A study session that breaks, or that completes while meaning
something other than what `STUDY_SURFACE_SPEC.md` and the records in `docs/`
promised: a reveal that reveals the wrong thing, a setting that is stored and
never applied. Pays in study time, which cannot be handed back close to an exam.

**Grounded in.** The study surface under `frontend/src/routes/` and the routers
behind it; #98, where `fixture-api.mjs` answered 200 to attempts the real server
refused with 412 while forty e2e tests stayed green; #106, where a real login's
`"default-learning-path"` became `NaN` behind a seeded numeric id; #105, where the
chosen language was saved and the UI stayed in the old one.

**Bears.** The broken session, found by using it. The e2e suite tests a double
with nothing pinning it to the server, so nothing earlier finds it.

**Vetoes.** A study-surface change whose only evidence is a green run against the
fixture.

## the operator at 5am

**Loss function.** Reading the ledger after an overnight milestone run and knowing
within a minute whether to intervene. Pays in false greens and in stalls that say
nothing.

**Grounded in.** The gates markers under `.claude/state/` with their `parity=` and
`ci-policy=` fields, the milestone ledger's `pipeline=` field, a median MR
pipeline of ~459s, and a run contract that is bound to one box: `SESSION_CMD`
stops working when the keyring credential goes stale, as it had on 2026-09-25,
and only an interactive login with an MFA code brings it back.

**Bears.** The run that stood still all night, and the green line that was really
an unconfigured check.

**Vetoes.** Anything that fails silently — an option whose failure mode leaves no
observable at all.

## the reader months later

**Loss function.** Opening Sophia with no context and finding out what was known
at the time. Pays in archaeology.

**Grounded in.** The accepted records in `docs/`, which bind; the `Fork:` lines in
commit bodies; the audit notes and `deferred-finding` issues, after #97..#103
recorded 42 deferrals and opened none; the alembic migrations that run on every
boot.

**Bears.** The re-litigation of a settled decision, and the bug fixed the same
wrong way twice.

**Vetoes.** A decision with no record of what was predicted, which is the one
thing that cannot be reconstructed later.
