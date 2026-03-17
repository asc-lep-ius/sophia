<!-- ──────────────────────────────────────────────────────────────────────────
     FEATURE REQUEST
     Use this template for new capabilities, enhancements, or user-facing changes.
     For broken behaviour → use bug-report. For chores/refactors → use task.
     ────────────────────────────────────────────────────────────────────────── -->

## Problem Statement

<!-- What pain point does this solve? Who experiences it?
     Example: "When a student has 6 open registrations on TISS, Kairos
     has no way to prioritise which one to attempt first, so it always
     tries them in arbitrary order and the time-sensitive ones fail." -->

## Proposed Solution

<!-- Your candidate approach — not the only valid one, just a starting point.
     Keep it short. The Acceptance Criteria below is what actually matters. -->

## Acceptance Criteria

<!-- Gherkin doubles as the contract between you and every contributor.
     Add as many Scenarios as needed. Title Case keywords are required
     for syntax highlighting to work. -->

```gherkin
Feature: <feature name, e.g. "Registration priority queue">

  Scenario: <happy path, e.g. "Highest-priority course registered first">
    Given <precondition>
    And <additional precondition if needed>
    When <action taken>
    Then <expected outcome>
    And <additional assertion if needed>

  Scenario: <edge case or failure path>
    Given <precondition>
    When <action taken>
    Then <expected outcome>
```

## Out of Scope

<!-- Explicitly list what this issue does NOT cover.
     This prevents well-meaning contributors from expanding scope.
     Example: "This issue covers prioritisation logic only — UI changes
     to expose the priority setting are tracked in #42." -->

- 

## Affected Module(s)

<!-- Tick whichever apply -->
- [ ] Bücherwurm (book discovery / acquisition)
- [ ] Kairos (TISS registration scheduler)
- [ ] Hermes (lecture knowledge base)
- [ ] Chronos (deadline tracking) — planned
- [ ] Athena (exam analysis) — planned
- [ ] Core / shared infrastructure
- [ ] CLI / UI
- [ ] Docs

## Implementation Notes

<!-- Optional: constraints, known pitfalls, related prior art in the codebase.
     Delete this section if you have nothing to add. -->

## For Contributors

<!-- Delete this section if you are the maintainer self-assigning.
     Leave it when the issue is open for external contribution. -->

Before starting:
1. Comment on this issue to claim it — avoids duplicate work.
2. Read [CONTRIBUTING.md](../../CONTRIBUTING.md) if you haven't already.
3. Open your draft PR early and link it here with `Closes #<this issue number>`.

---

/label ~"feature-request" ~"needs-triage"
