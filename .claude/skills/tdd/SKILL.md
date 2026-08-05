---
name: tdd
description: Use whenever implementing a new behaviour, fixing a bug, or changing existing behaviour in this repository. Enforces asking clarifying questions before coding, then a strict red-green-refactor cycle — a failing test first, confirmed red, then the minimal implementation, confirmed green. Do not write production code without a test that demanded it.
---

# Test-driven development, genuinely

This project's standing rule (see `AGENTS.md`, "How to work on it"): **no production
code without a test that demanded it.** This skill is how to follow that rule
instead of skipping it under time pressure.

## 1. Ask before writing anything

Before touching a test or a source file, make sure the behaviour is actually
pinned down. If any of the following is unclear from the request, the existing
code, or `AGENTS.md`/`docs/adr/`, ask the user rather than guessing:

- What is the exact input/output or before/after behaviour expected?
- What are the edge cases — empty input, missing prerequisite, abandonment,
  malformed data — and what should happen for each?
- Does this touch one of the four seams (`GitBackend`, `GitHubClient`,
  `Environment`, `Ui`)? If so, which one, and does a fake already exist for it?
- Is this a presentation change (governed by `docs/CONVENTIONS.md`) or a behaviour
  change? Behaviour changes to menu structure, module layout, or a stated
  invariant need the maintainer's sign-off before writing code — say so and ask.

Do not proceed on an assumption you could instead confirm in one question. Batch
questions together rather than trickling them one at a time.

## 2. Red — write the failing test first

Write the smallest test that pins down the behaviour just confirmed. Run it and
read the failure. It must fail for the reason you expect (missing behaviour), not
for an unrelated reason (typo, import error, wrong fixture). If it fails for the
wrong reason, fix the test before writing any implementation.

Show the user the failing test output, or at minimum state plainly that it went
red and why, before moving on.

## 3. Green — the minimal implementation

Write only enough production code to make that test pass — no speculative
generality, no unrelated cleanup, no untested branches. Run the test again and
confirm it passes. Run the full suite (`make test`) to confirm nothing else broke.

## 4. Refactor

With the test green, tidy the implementation if it needs it — naming, duplication,
structure — without changing behaviour. Re-run the tests after refactoring; they
must still pass unchanged.

## 5. Repeat

One behaviour per cycle. For multi-part work, go back to step 1 for the next
behaviour rather than batching several behaviours into one red-green pass — a
red that covers three behaviours at once hides which one is actually done.

## Non-negotiables

- Never write implementation code before its test exists and has been observed to
  fail.
- Never mark a cycle done without having actually run the test suite (not just
  read the code and assumed it would pass).
- If you find yourself having written untested code, delete it and redo the cycle
  properly rather than writing a test to retroactively justify it.
- `make check` (lint + types + test) must be clean before considering the work
  finished.
