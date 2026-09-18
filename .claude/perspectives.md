# Perspectives

The seats `/council` may convene on a fork in this project. Copy this file to
`.claude/perspectives.md` and replace the seats below with the ones this project
actually has; `convene.sh` checks every seat name against the `##` headings here,
so a seat nobody wrote down is refused rather than quietly counted.

**A perspective earns a seat only if both are true**: its loss function conflicts
with another seat's *on this fork*, and it bears a cost if the decision is wrong.
Derive the seats from the blast radius — who implements and pays, who owns the
domain's ontology, who holds a veto — and ground each one in something named: the
artefact it reads, the measurement it is judged on, the incident it remembers. A
title is not grounding. Role labels bought no accuracy across 162 personas and
2,410 questions (Zheng et al., EMNLP Findings 2024); what a seat is worth is the
cost it carries.

**Cap at three.** Two seats that would score every option alike are one seat, and
`convene.sh` says so in the render when it sees it. Three seats are also not three
votes — one model wearing three system prompts is correlated judging at its worst
(arXiv 2605.29800), which is why the output is the objections and not the
agreement.

**Never convene for**: a trivial fork; a fork a cheap measurement answers — run
the measurement; a fork the decision boundary already owns, in either direction.

---

## the implementer

**Loss function.** Getting it built, attributed and measurable inside the time
there is. Pays in rework and in work that cannot be shown to have helped.

**Grounded in.** The last three things that took twice their estimate, and what
made them; the gates in `.claude/gates.sh` and what they cost per turn.

**Bears.** Every hour of the rework, and the explaining if the measurement never
arrives.

**Vetoes.** Nothing. A cost is not a veto.

## the operator at 5am

**Loss function.** Reading one ledger, half awake, and knowing within a minute
whether to intervene. Pays in false alarms and in silent failures.

**Grounded in.** The log lines and state files this project actually writes, and
the last incident where the signal was there but unreadable.

**Bears.** The pages, and the outage that ran long because the ledger did not say
what had already been tried.

**Vetoes.** Anything that fails silently — an option whose failure mode leaves no
observable at all.

## the reader months later

**Loss function.** Opening this repo with no context and finding out what was
known at the time. Pays in archaeology.

**Grounded in.** The audit notes and deferred findings on the issues; what `git
blame` reaches from a line of code; what a decision recorded here would still
mean after the people are gone.

**Bears.** The re-litigation, and the bug that is fixed the same wrong way twice.

**Vetoes.** A decision with no record of what was predicted, which is the one
thing that cannot be reconstructed later.
