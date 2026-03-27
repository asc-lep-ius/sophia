<!-- ──────────────────────────────────────────────────────────────────────────
     FEATURE REQUEST
     Use this template for new capabilities, enhancements, or user-facing changes.
     For broken behaviour → use bug-report. For chores/refactors → use task.
     ────────────────────────────────────────────────────────────────────────── -->

## 🎉 Problem Statement

<!-- What pain point does this solve? Who experiences it?
     Example: "When a student has 6 open registrations on TISS, Kairos
     has no way to prioritise which one to attempt first, so it always
     tries them in arbitrary order and the time-sensitive ones fail." -->

## 💁 User Story

> As a **[persona]**, I want to **[action]**, so that **[benefit]**.

<!-- Personas: student (cramming), student (planning), power user (CLI), casual user (GUI) -->

## 💡 Proposed Solution

<!-- Your candidate approach — not the only valid one, just a starting point.
     Keep it short. The Acceptance Criteria below is what actually matters. -->

## 🎯 Acceptance Criteria

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

## 🛡️ Abuse & Misuse Cases

<!-- Abuse = intentional malicious actions. Misuse = accidental but harmful. Delete if not applicable. -->

- **Abuse:** <!-- e.g. "Attacker crafts a malicious TISS session cookie to exfiltrate data." -->
- **Misuse:** <!-- e.g. "User accidentally triggers bulk registration for all courses." -->
- **Mitigation:** <!-- e.g. "Rate-limit TISS API calls; require confirmation for bulk actions." -->

## 🧪 Test Planning

- **E2E Scenarios:** <!-- List critical user flows to validate -->
- **Integration Tests:** <!-- List systems/APIs involved -->
- **UI Test Coverage:** <!-- Visual states or screenshot requirements -->

## 🚫 Out of Scope

<!-- Explicitly list what this issue does NOT cover.
     This prevents well-meaning contributors from expanding scope.
     Example: "This issue covers prioritisation logic only — UI changes
     to expose the priority setting are tracked in #42." -->

- 

## 📦 Affected Module(s)

<!-- Tick whichever apply -->
- [ ] Bücherwurm (book discovery / acquisition)
- [ ] Kairos (TISS registration scheduler)
- [ ] Hermes (lecture knowledge base)
- [ ] Chronos (deadline tracking) — planned
- [ ] Athena (exam analysis) — planned
- [ ] Core / shared infrastructure
- [ ] CLI / UI
- [ ] Docs

## 🤓 Implementation Steps

<!-- Reserved for developers. Add numbered steps with estimates. -->

1. <!-- Step description — (estimate) -->

## 🤝 For Contributors

<!-- Delete this section if you are the maintainer self-assigning.
     Leave it when the issue is open for external contribution. -->

Before starting:
1. Comment on this issue to claim it — avoids duplicate work.
2. Read [CONTRIBUTING.md](../../CONTRIBUTING.md) if you haven't already.
3. Open your draft PR early and link it here with `Closes #<this issue number>`.

## ✅ Definition of Ready

- [ ] Scope fits a single iteration (not a hidden epic)
- [ ] Acceptance criteria written in Gherkin
- [ ] Edge cases identified
- [ ] No open questions remaining
- [ ] Abuse/misuse cases considered (if user-facing)

---

/label ~"feature-request" ~"needs-triage"
