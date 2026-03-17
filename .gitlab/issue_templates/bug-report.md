<!-- ──────────────────────────────────────────────────────────────────────────
     BUG REPORT
     Use this template for broken or incorrect behaviour.
     For new capabilities → use feature-request. For chores → use task.
     ────────────────────────────────────────────────────────────────────────── -->

## Summary

<!-- One sentence: what broke, in which module, under what condition.
     Example: "Bücherwurm raises KeyError when a TISS course has no
     assigned ISBN and the --strict flag is passed." -->

## Environment

<!-- Fill in what applies. This matters because Sophia talks to live university
     systems that differ by semester, account type, and region. -->

| Field | Value |
|---|---|
| Sophia version / commit | <!-- `git rev-parse --short HEAD` --> |
| Python version | <!-- `python --version` --> |
| OS | <!-- e.g. Ubuntu 24.04, macOS 15, Windows 11 --> |
| Auth method | <!-- TUWEL cookie / TISS OAuth / other --> |
| Affected module | <!-- Bücherwurm / Kairos / Hermes / … --> |

## Steps to Reproduce

<!-- Numbered, specific steps. Include the exact command you ran.
     If a config file or fixture is needed, attach it or paste a minimal example. -->

1. 
2. 
3. 

## Actual Behavior

<!-- What did Sophia actually do? Paste the full error output (stack trace, log
     lines) inside a code block if applicable. -->

```
paste error / unexpected output here
```

## Expected Behavior

<!-- What should have happened instead? -->

## Acceptance Criteria

<!-- What does "fixed" look like? One or two Scenarios is usually enough for a bug. -->

```gherkin
Feature: <the behaviour that was broken>

  Scenario: <normal case that should work again>
    Given <precondition that previously triggered the bug>
    When <action that caused the error>
    Then <correct outcome>

  Scenario: <regression guard — ensure the original trigger no longer breaks>
    Given <the exact environment from "Steps to Reproduce">
    When <same action>
    Then <no error, correct output>
```

## Affected Module(s)

- [ ] Bücherwurm
- [ ] Kairos
- [ ] Hermes
- [ ] Chronos
- [ ] Athena
- [ ] Core / shared infrastructure
- [ ] CLI / UI

## Additional Context

<!-- Screenshots, log files, related issues, external docs — anything else useful.
     Delete this section if empty. -->

---

/label ~bug ~"needs-triage"
