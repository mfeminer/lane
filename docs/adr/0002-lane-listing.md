# ADR 0002 — The lane listing

- **Status:** accepted and implemented in 0.0.2
- **Date:** 2026-08-05
- **Decides:** what the listing screen is, how it is acted on, what it replaces in
  the menu, and how the `Ui` seam widens to carry it

## Context

The listing works and answers nothing well. Three faults, in the order they matter.

**Looking and acting are separate widgets.** You read a table, the table stops
being interactive, and a different list appears underneath asking what to do.
Nothing connects a row to the entry that acts on it except reading the name twice
and matching it by eye.

**The action list is the cross product of lanes and verbs.** Two lanes and two
verbs already produce four entries plus a way back; five lanes would produce
eleven. Every entry repeats the full `project/lane` path, so the part that actually
differs — `enter` versus `close` — is the least visible thing on the line.

**The dim indented lines repeat the table.** A lane's name is `slugify` of its
description, so `improve-lint-and-format-performance` and `improve lint and format
performance` are the same string rendered twice, in two places.

Underneath all three: the screen was designed as *output*, and the interaction was
bolted on afterwards as a second prompt. This ADR makes the listing a screen the
user stands in.

### What the listing is for

Two questions, both of which it should answer without being asked for anything:

1. **What am I in the middle of?**
2. **Which of these can I close, and what is stopping the ones that cannot?**

Question 2 is the one the current screen answers worst: `state` and `pr` are the
columns that carry the answer and they are the narrowest things on the line, while
`lane` and `branch` — which say the same thing twice, the second with a prefix —
take about ninety columns between them.

## Decision

One screen. A cursor moves over the rows; the row under the cursor is the subject
of whatever happens next. `list`, `enter` and `close` collapse into a single menu
entry, `lanes`. The columns are re-cut so the two questions are answered by what is
widest, not by what is narrowest. Everything a row cannot carry goes into a
three-line panel that follows the cursor. **No new keys are introduced**: the table
binds exactly what the picker already binds.

---

## The four questions

### 1. Is a separate detail view needed? — Yes, as a panel that follows the cursor

**Recommendation: a fixed panel under the table, showing the row under the cursor.
Not an expanding row, not a separate screen.**

The case against any detail view is real: the close flow already prints the full
diagnosis — dirty files, unpushed commits, pull request state — before it asks for
confirmation, so a detail view risks being that information shown twice. The case
for it is also real: *"what is the state of this lane"* is worth answering without
committing to closing it, and there is one thing the close flow cannot tell you at
all, because it never runs — **why the `pr` column says `unknown`**. A cell reading
`unknown` with no remedy anywhere on screen is a worse cell than no cell.

So the panel is admitted, and then kept honest by a strict rule:

> **The panel shows only what `collect` already knows.** It never issues a git or
> `gh` call of its own.

That rule settles the duplication worry by construction. Which files are dirty and
which commits are unpushed cost a git call per lane and stay in the close flow,
where they change a decision. The panel carries the three things the row had to
drop and the close flow will not print: the branch, the description when it differs
from the name, and one sentence about the pull request. Two or three lines, no
latency, no second widget.

Between the three shapes:

- **A panel that follows the cursor** — always in the same place, so moving the
  cursor never moves anything except the cursor.
- **An expanding row** — rejected. Expanding changes the geometry of every row
  below it, so the row you were reaching for slides away as you arrive. That is a
  bad property in a list whose whole purpose is to be moved through.
- **A separate screen** — rejected. It is a mode you enter and leave, which is
  exactly the second-widget disease this ADR exists to cure. It would also
  reintroduce the disconnect: you would read the detail, leave it, and then find
  the row again.

When the terminal is too short to hold both the table and the panel, the panel is
dropped and the table keeps the space. The table answers the questions; the panel
elaborates.

### 2. Should this replace three menu entries with one? — Yes

**Recommendation: the menu becomes `open`, `lanes`, `settings`, `doctor`,
`changelog`, `quit`.**

`enter` and `close` both begin by asking *which lane* — using `choose_lane`, which
renders the same lanes as the listing with none of the status. They are strictly
worse routes to the same place: same picking, less information. Removing them
removes a worse path, not an action.

This does not touch the rule that the menu is always the full list. That rule is
about **hiding** entries behind unmet prerequisites, and its reason — a user who
cannot see an action cannot find out why it is unavailable — does not apply here.
Entering and closing are not hidden; they are one Enter away from the screen that
shows you which lanes there are to enter and close, which is a better place to find
them than a menu that cannot show you any.

`list` is renamed `lanes` because it is no longer only a list.

The counter-argument, stated fairly: someone who already knows they want to close a
lane now pays one extra keypress. That is the correct trade. lane is touched at the
two ends of a working day, twice; the cost of a keystroke there is close to nothing,
and the disconnect the maintainer is complaining about comes precisely from having
split looking and acting into separate menu items.

### 3. How are the actions triggered? — Enter opens the row's action menu

**Recommendation: `Enter` on a row opens a two-entry menu for that row — `enter`,
`close` — using the existing `choose`. No letter keys.**

The alternative — direct keys with a footer legend (`⏎` enter, `c` close) — is
faster, and the maintainer is right that the close flow's check-and-confirm pass is
the real safeguard, so a mis-keyed `c` is an annoyance rather than a danger. It is
still the wrong call here, for two reasons.

**The first is the standing rule.** AGENTS.md removed `q`, `j`/`k` and the digit
shortcuts and wrote down why: *"If a key is not one a user would already expect
from any other terminal program, it does not belong."* `c` for close is precisely
this tool's invention, in the same class as the keys that were removed. A footer
legend makes it discoverable, which answers the *teaching* objection but not the
*consistency* one — every other prompt in lane would still bind arrows, Enter and
nothing else.

**The second is that it costs nothing to obey.** The table needs `↑` `↓` `Home`
`End` `Enter` `Ctrl-C` — the picker's exact bindings. Choose the nested menu and
the redesign introduces **no new key vocabulary at all**: the key table in
AGENTS.md stays true as written, and the thirty lines it spends explaining why keys
are dangerous do not have to be revisited.

The nesting objection is answered by what the nested menu contains. The complaint
was that the second widget re-lists the *lanes*; this one lists **verbs**, two of
them, titled with the lane it applies to. The cross product is gone: two lanes and
two verbs produce two rows and a two-entry menu, and five lanes still produce a
two-entry menu.

Backing out of the row menu returns to the table, not to the main menu — the table
is a screen you are standing in, not a question you were asked.

*If the maintainer prefers the letter keys anyway*, the change is small and
localised: the table gains a `RowAction` list, binds each action's key, and renders
a legend in the footer; the row menu disappears; AGENTS.md's key table grows a
"listing only" column. Everything else in this ADR is unaffected. Say so and it
will be built that way.

### 4. What does each row show? — The name, and the description only when it differs

**Recommendation: the lane name is primary. The description appears in the panel,
and only when it is not the same information.**

The name is the lane's identity: it is the directory, it is in the branch, and it
is what the editor's window title will say. The description is what it was made
from. They differ in exactly three cases — a description longer than the 40-char
cap, a description with non-ASCII characters (`Login sayfası hatası` →
`login-sayfasi-hatasi`), and a lane whose metadata has gone missing (where the
description *is* the name).

So the rule is mechanical:

> Show the description in the panel when the lane name is *not* that description
> with its punctuation swapped for hyphens.

**Corrected while implementing.** The rule first written here was
`slugify(description) != name`, and the test for the non-ASCII case failed against
it — correctly. `slugify` is what *produced* the name, so comparing against it
suppresses exactly the accented spellings worth keeping: `Login sayfası hatası`
round-trips to `login-sayfasi-hatasi`, and under the original rule the Turkish
spelling the user actually typed would never be shown. The narrower comparison —
lowercase, non-alphanumerics to hyphens, no transliteration — keeps it, and still
suppresses `Improve the export`, which is the fault this was written to fix.

On the maintainer's own screen, both descriptions round-trip exactly, so neither
row shows one — which is the right outcome and the direct fix for fault three.

The project prefix gets the same treatment. `Acme.Widgets/` on every row is thirteen
columns of the same string, so: **when every lane belongs to one project, the title
carries the project and the column shows bare names.** When lanes span projects, the
column shows `project/name` with the project dimmed.

---

## The screen

### Columns

| Column | What it is | Dropped when narrow |
|---|---|---|
| `lane` | the lane name; `project/name` when projects are mixed | never — truncates last |
| `state` | the answer to question 2 | never |
| `pr` | pull request state, including "cannot tell" | never |
| `age` | how long this lane has been open | first |

`branch` **loses its column** and moves to the panel. On the maintainer's screen it
spends forty columns on `chore/` plus the string the first column just showed. What
was load-bearing about it is not the text but two facts, and both are states rather
than names: *is this detached* (it changes what closing does) and *what kind of work
is this* (which the lane name already says). Detachment moves into `state`, where it
belongs; the full ref stays one line away in the panel, for the row you are looking
at.

Degradation order is `age`, then the project prefix in `lane`, then the lane name
truncates at the end with `…`. `state` and `pr` are never dropped and never
truncated: dropping them would leave a listing that cannot answer the question it
exists for.

### The `state` cell

| Condition | Cell | Tone |
|---|---|---|
| status could not be read | the reason, capped | bad |
| uncommitted and/or unpushed | `● 2 uncommitted`, `↑ 3 unpushed`, or both joined by `·` | warn |
| detached | prefixed `detached · ` | warn |
| own commits reached the base | `✓ merged` | good |
| no commits of its own | `no commits yet` | dim |
| otherwise | `not merged yet` | warn |

This is today's wording, unchanged, including the invariant that **`merged` is only
said of a lane that has commits which reached the base**. What changes is that it is
now given room and colour.

### The `pr` cell

| Answer | Cell | Panel line |
|---|---|---|
| still being fetched | `checking…` (dim) | `Checking GitHub for a pull request…` |
| `Found` | `#418 open` / `merged` / `closed` | the URL |
| `NoPullRequest` | `none` (dim) | `No pull request for this branch yet.` |
| `CannotTell` | `unknown` (bad) | the reason **and the remedy** |
| `NotApplicable` | `—` (dim) | `origin is not a GitHub remote` / `detached HEAD — no branch to have one` |

`none` and `unknown` are different answers and are shown as different words:
`none` means GitHub was asked and said no, `unknown` means it could not be asked.
The panel turns `unknown` from a dead end into an instruction — `gh is not
installed. Fix with: brew install gh` — which is the single clearest thing the
panel buys.

### Order, and why it never changes

Rows are sorted by project, then name — what `LaneStore.list_lanes` already
returns. **The order does not change while the screen is up**, in particular not as
pull request answers arrive. Sorting by "closeable first" was considered and
rejected: rows that rearrange themselves under a cursor are unusable, and the
listing's job is to be looked at, not to have an opinion.

### The footer

`  ↑↓ move · enter choose` — the picker's existing footer string, unchanged. When
the rows do not all fit, it gains a range: `  ↑↓ move · enter choose · 1–8 of 14`.

### Scrolling

The rows are a window into the list. The cursor scrolls the window when it reaches
an edge; `Home` and `End` jump to the ends; moving past either end wraps, as the
picker already does. The window's height is what is left after the title, the
header, the `← Back` row, the panel and the footer, with a floor of three rows —
below which the panel is dropped first, and then the header.

---

## Rendered mocks

### Two lanes — settled

```
  2 open lanes in Acme.Widgets

  lane                                   state            pr         age
❯ improve-lint-and-format-performance     no commits yet   none       today
  local-development-artifact-management   ● 2 uncommitted  #418 open  today
  ← Back to the menu

  chore/improve-lint-and-format-performance
  No pull request for this branch yet.

  ↑↓ move · enter choose
```

Neither row shows a description: both round-trip through `slugify` unchanged, which
is the rule from question 4 doing its job. `Acme.Widgets` appears once, in the
title. The two columns that answer question 2 sit in the middle of the line rather
than at the end of it.

Pressing Enter on the second row:

```
Acme.Widgets/local-development-artifact-management

  ❯ enter    relaunch the editor in this lane
    close    safety checks, then remove the worktree
    ← Back

  ↑↓ move · enter choose
```

Two entries and a way back, for any number of lanes. Backing out here returns to
the table with the cursor where it was.

### Zero lanes

```
  No open lanes. Open one from the menu.
```

No table, no headers, no cursor, no `← Back` row. It says so and returns to the
menu, which is where opening a lane is.

### Pull request state still loading

The first paint, before any `gh` process has finished:

```
  2 open lanes in Acme.Widgets

  lane                                   state            pr          age
❯ improve-lint-and-format-performance     no commits yet   checking…   today
  local-development-artifact-management   ● 2 uncommitted  checking…   today
  ← Back to the menu

  chore/improve-lint-and-format-performance
  Checking GitHub for a pull request…

  ↑↓ move · enter choose
```

Everything git can answer locally is already on screen and the cursor already
moves; the `pr` cells fill in one at a time as each `gh` call returns. Choosing a
row while they are still pending is allowed and does not wait for them — the close
flow does its own pull request lookup, and entering a lane never needed one.

### A lane whose pull request state cannot be told

```
  2 open lanes in Acme.Widgets

  lane                                   state            pr        age
❯ improve-lint-and-format-performance     no commits yet   unknown   today
  local-development-artifact-management   ● 2 uncommitted  unknown   today
  ← Back to the menu

  chore/improve-lint-and-format-performance
  Pull request state unknown — gh is not installed. Fix with: brew install gh

  ↑↓ move · enter choose
```

### A narrow terminal

At roughly sixty columns, `age` is gone and the lane name has truncated; `state`
and `pr` are untouched.

```
  2 open lanes in Acme.Widgets

  lane                             state            pr
❯ improve-lint-and-format-perfor…  no commits yet   none
  local-development-artifact-man…  ● 2 uncommitted  #418 open
  ← Back to the menu
```

---

## What happens after each action

| Action | Afterwards | Why |
|---|---|---|
| `close` | **stay in the listing**, one row shorter | Closing several lanes in a row is a real batch: they land together. The cursor keeps its index, clamped, so it sits on the row that took the closed one's place. |
| `enter` | **return to the menu** | Your attention has moved to the editor. Holding the listing up implies there is more to do on this screen, and its data is about to go stale — you are on your way to change that lane. |

The asymmetry is deliberate and is the answer to *"returning to the main menu after
every action is part of what makes the current flow tiring"*: it is closing that
repeats, not entering.

Re-collecting after a close re-runs the git status pass — local and fast — and
**reuses the pull request answers already collected** for the lanes that are still
there. The second paint is immediate.

---

## The seam

The interactive table sits below the `Ui` seam, exactly as the picker does: a
component with its own tests, driven through `prompt_toolkit`'s pipe input. The
action asks for a screen and gets an answer back; it does not know a table exists.

The seam **trades a method rather than accumulating one**. `Ui.table` — tell-only,
and used by nothing but the listing — is removed along with `render.print_table`,
and `Ui.browse` takes its place.

```python
type Tone = Literal["", "good", "warn", "bad", "dim"]


@dataclass(frozen=True, slots=True)
class Cell:
    text: str
    tone: Tone = ""  # meaning, not colour: the widget picks the colour


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    drop: int = 0  # higher goes first when narrow; 0 is never dropped


@dataclass(frozen=True, slots=True)
class Row[T]:
    value: T
    cells: tuple[Cell, ...]
    detail: tuple[str, ...] = ()  # the panel, for when the cursor is on this row


type Fill = Callable[[Callable[[], None]], None]
"""Fill in the slow cells, calling `notify` each time one lands."""


def browse[T](
    self,
    title: str,
    columns: Sequence[Column],
    rows: Callable[[], Sequence[Row[T]]],
    *,
    back: str = BACK_LABEL,
    fill: Fill | None = None,
    cursor: int = 0,
    on_render: Callable[[str], None] | None = None,
) -> tuple[T, int]:
    """The row under the cursor when Enter was pressed, and where it was.

    The visible `back` row and Ctrl-C both raise `Abandoned`, as in `choose`.
    """
```

Three things are worth the words:

**`rows` is a callable, not a sequence.** It is called on every repaint, so the
table always draws what is currently known. The action owns the data and the
locking; the widget owns the drawing.

**`fill` is handed *to* the UI rather than started by the action.** The real UI runs
it on a thread and wires `notify` to `Application.invalidate`, so the first paint
never waits. `FakeUi` runs it synchronously with a no-op `notify`, so a scripted
test sees a fully settled table with no timing in it. That one asymmetry is what
makes "render what is known, fill the rest in" testable at all without sleeps.

**`cursor` goes in and comes out**, which is how the listing puts you back where you
were after an action instead of at the top.

### Driving it from a script

`FakeUi.browse` answers the way `FakeUi.choose` does — by matching against any of
the row's cell texts, or the value itself, or an integer row index. So *"select the
second lane, close it"* is either of:

```python
FakeUi(["thing/clean-lane", "close", True])
FakeUi([1, "close", True])
```

and session-level tests keep replacing the whole seam, never reaching the widget.

### One thing the listing is allowed to do that no other action is

The listing **catches `Abandoned` around the row menu** so that backing out of it
returns to the table rather than to the main menu. It is the only place in the
application where an action catches it, and it is safe for the same structural
reason as everywhere else: every question still comes before the first irreversible
step, so an abandoned row menu has changed nothing. This goes in AGENTS.md as a
named exception rather than being left to be discovered.

---

## What is deliberately not built

- **No sort control and no new state-file key.** The order is fixed and
  predictable, which is worth more here than configurability; a remembered cursor
  that is a day stale is worse than one that is always at the top. If the maintainer
  wants either later, the state file is the place and it needs no asking.
- **No refresh key.** Leaving the screen and coming back re-collects. A key that
  exists to re-run something the screen already ran on entry is a key that should
  not exist.
- **No path in the panel.** It is `<lanes_root>/<project>/<lane>`, all three of
  which are on screen or in settings, and AGENTS.md is explicit that lane does not
  hand out paths for shells to consume.
- **No new dependency.** `prompt_toolkit` draws the table; `rich` keeps everything
  it already does.

## Consequences

- `actions/enter_lane.py` keeps `enter(context, lane)` — the editor launch and its
  missing-editor warning, in one place — and loses its `run(context)` entry point.
- `close_lane.run` and `picking.choose_lane` become unreachable and are deleted;
  `close_lane.close_specific` is the whole of closing, and is renamed `close`.
- `Ui.table`, `ConsoleUi.table`, `FakeUi.table` and `render.print_table` are
  deleted.
- `AGENTS.md` changes in the same commit: the actions list, the listing's
  behaviour-to-preserve line (branch moves to the panel), the seam table's `Ui` row,
  and a new invariant that the listing is one screen with no keys of its own.
- `docs/PLAN.md`'s menu table changes and gains Phase K.
- `README.md`'s menu block and listing section change; a stale README is the same
  fault as a stale briefing.
- **Version.** `0.0.2`, with a changelog entry. The three tests that hard-coded
  `0.0.1` now assert against `__version__` — they were about the *format* of the
  version line, never about a particular number.

## Implementation order

Test-first throughout, each box one red-green-refactor cycle.

**The widget** (`src/lane/ui/table.py`, `tests/test_table.py`, pipe input):

1. Enter returns the row under the cursor and its index.
2. `↑` `↓` move; movement wraps at both ends.
3. `Home` and `End` jump to the ends.
4. The visible `← Back` row is last, and Enter on it raises `Abandoned`.
5. `Ctrl-C` raises `Abandoned`; Option+Left does not, as in the picker.
6. An unrecognised key is ignored and the table stays up.
7. `cursor=` starts the cursor on a given row.
8. A `fill` that never returns does not stop the first paint or the first Enter.
9. `fill`'s `notify` causes a repaint that shows the new cell.
10. Too narrow: `age` goes, then the lane name truncates; `state` and `pr` survive.
11. Too many rows: a window is drawn and the footer says which one.
12. The panel shows the cursor row's detail lines and follows the cursor.
13. Too short: the panel is dropped before any row is.

**The seam** (`tests/test_going_back.py`):

14. `ConsoleUi.browse` appends the visible `← Back` row.

One more box was added while building, found by driving the real binary through a
pty: **backing out of the row menu must not rebuild the table.** It changed nothing,
so re-reading every lane's status only puts the spinner back on screen and flickers.
The table is rebuilt after a close and at no other time.

**The action** (`src/lane/actions/list_lanes.py`, `tests/test_listing.py`):

15. Zero lanes: says so, renders no table, asks nothing.
16. Rows carry lane, state, pr and age; `merged` still is not said of a fresh lane.
17. Pull request state appears inline (`#418 open`).
18. `gh` unavailable renders `unknown` — distinct from `none` — and the panel
    carries the remedy.
19. A `GitHubClient` that raises still renders the listing.
20. The rows are complete, with `checking…` in `pr`, **before** `fill` runs.
21. After `fill`, the same rows carry their pull request answers.
22. The description is in the panel only when `slugify(description) != name`.
23. The project is in the title when all lanes share one, and in the column when
    they do not.
24. Choosing a row then `enter` launches the editor and returns to the menu.
25. Choosing a row then `close` closes it and **stays in the listing**, one row
    shorter, with the cursor clamped.
26. Backing out of the row menu returns to the table; backing out of the table
    returns to the menu.
27. Status is still collected across a thread pool for many lanes.

**The menu** (`tests/test_session.py`):

28. The menu is `open`, `lanes`, `settings`, `doctor`, `changelog`, `quit`, and
    `enter` and `close` are gone from it.
29. End to end: menu → open → menu → lanes → select the lane → close → back →
    quit, asserting the resulting git state.
