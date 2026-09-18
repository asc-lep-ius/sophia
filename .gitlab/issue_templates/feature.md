<!-- ──────────────────────────────────────────────────────────────────────────
     FEATURE
     A change to what the product does for the person using it.

     Scenario 1 is the point of this template. It is the user's own sentence —
     who signs in, what they do, what they see — walked end to end on the real
     stack. Everything else queues behind it: latency, coverage, touch targets
     and scoring rules are all true, all testable, and not one of them is a
     person completing the flow.

     An issue written this way can go first, which matters because /milestone
     orders a queue by vertical slice and refuses one that does not open on a
     path a user can walk. A milestone of layers ships its first walkable path
     last, and nobody finds out until the last layer lands.

     Delete the sections that do not apply; a blank section is worse than none.
     ────────────────────────────────────────────────────────────────────────── -->

## What the user can do that they cannot do today

<!-- One sentence, in their words, naming the person and the outcome — not the
     component. "A learner can grade a card and see the next one" is one; "the
     review engine is wired to the scheduler" is not. -->

## Acceptance scenarios

### Scenario 1 — the flow, end to end

<!-- The walking skeleton for this issue. Three rules: a signed-in person, the
     real stack rather than a fixture, and one outcome they can observe. If a
     stub backend that accepts everything could satisfy it, it is not scenario 1
     yet — that is the shape that let four review rounds approve a login-to-study
     flow which had never once completed. -->

```gherkin
Given a signed-in <role>
When they <the one thing this issue is for>
Then they see <the outcome, worded as the user would word it>
```

<!-- No UI — a queue, a job, an API? The same sentence holds with a client in
     place of the browser: "Given a client authenticated as <role> / When it
     POSTs <…> / Then it receives <…> and <the side effect> is visible at <…>".
     What it may not become is "the handler exists". -->

### Scenarios 2..n — the quality attributes

<!-- Latency, limits, permissions, sizes, empty and error states — each one a
     scenario of its own. These are the criteria a reviewer can tick without
     anyone ever having used the product, which is exactly why they come after
     the flow rather than instead of it. -->

## Out of scope

- 

## Dependencies

| Relationship | Issue |
|---|---|
| Follows | <!-- #N or n/a --> |
| Blocks | <!-- #N or n/a --> |

## Acceptance criteria

- [ ] Scenario 1 was walked end to end on the real stack — started the way `RUN_CMD` starts it, signed in the way `SESSION_CMD` signs in — and somebody watched it happen
- [ ] Every scenario below it has a test that would fail if the feature were removed
- [ ] 

## Touches

<!-- One line: the routes, components and modules this lands in. Labels carry the type. -->


---

/label ~feature
