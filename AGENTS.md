# AGENTS.md — briefing for a fresh session

This is the first thing to read. It is written so that a session with no memory of
any previous one can pick the work up cold. When a decision changes, this file
changes in the same commit: a stale briefing is worse than none.

---

## What lane is

`lane` runs several pieces of work side by side, each in its own git worktree.
A **lane** is one task: its own working copy, its own branch, its own editor
window. You open a lane when you start something and close it when it has landed.

The working day, which the whole design serves:

1. Run `lane`, open a lane. The editor launches in the new worktree.
2. Do all the work there — the editor's integrated terminal is already inside it.
3. Quit the editor.
4. Run `lane` again and close the lane: it checks the pull request, verifies
   nothing is left behind, and cleans up the worktree.

lane is touched at **the two ends only**. It is not part of the edit-test loop.
This is the single most important thing to keep in mind when judging whether a
feature belongs: if it would be used mid-loop, it does not.

## The interaction model — a menu for a person, subcommands for everything else

Running `lane` bare starts an interactive session:

- it shows a menu of everything lane can do
- you choose an action and lane walks you through it with prompts
- when the action finishes you are back at the menu
- the session ends when you choose to quit

**And `lane` takes subcommands: `open`, `list`, `enter`, `close`, `doctor`.** This
file used to say, at length, that it never would. That was reasoned from a premise
which has since changed, so the reasoning is replaced rather than quietly dropped.

**What the old rule said, and why it was right at the time.** Two entry points mean
two things to keep in step, and the menu matched how lane was actually used: twice a
day, from a shell nobody was scripting. Every other decision on this page followed
from a person sitting at a terminal — a TTY is required, there is no machine-readable
output, the help text is a paragraph explaining that there is nothing else to type.

**What changed.** lane is now driven by scripts and by AI agents as well as by a
person. Neither can move a cursor over a table, and neither can answer a prompt it
cannot see. A tool that can only be used by hand is, for them, a tool that cannot be
used at all — and "run lane and click through the menu" is not something a script can
be told to do. That is a change of premise, not a change of taste, and the old rule
does not survive it.

**What has not changed, and is the whole of why this is safe.** A subcommand does
not *do* anything. It answers, in advance, the questions the interactive flow was
going to ask, and then runs **that same action** — `open_lane.open_a_lane`,
`enter_lane.enter`, `close_lane.close`, `doctor.checks`. The device that makes this
possible is `cli/answers.py`: a `Ui` that sits exactly where the real one sits, hands
back the answers it already has, and falls through to the real prompt for the rest.
So there is one implementation of what opening a lane means, and the second entry
point is a second *caller*, never a second copy. `tests/test_cli_commands.py` asserts
that — a subcommand growing its own version of a flow fails there rather than in a
bug report a year later.

**Subcommands, not top-level flags.** `lane open`, not `lane --open`: the noun/verb
shape every tool in this space uses (`git`, `gh`, `docker`, `kubectl`; clig.dev).
Introducing both would be the drift the old rule feared, for real this time.

**Two tables, and the difference between them is the point.** The menu is still
generated from `ACTIONS` and nothing else, so it cannot drift from what the app can
do. The subcommands come from `cli/parser.COMMANDS`. They overlap without being the
same list, and both of the differences are deliberate:

- `enter` and `close` are subcommands but **not** menu entries. They are the two verbs
  the listing offers for the row under the cursor, and that is still the better route
  by hand — see below. A script has no cursor, so it names the lane instead.
- `settings` is a menu entry and **not** a subcommand, yet. Configuring lane from a
  script is a real want and is its own piece of work; until then the absence is stated
  rather than half-built.

What the two tables share is the action function. What they do not share is the list
itself, and a new action is not automatically scriptable — that is a decision to take
per action, not a gap to fill in reflexively.

**A `<project>/<lane>` names a lane, and nothing else does.** `lane enter demo/pager`,
`lane close demo/pager` — the same slug the listing prints on every row. This does not
contradict *looking and acting are the same widget*: the cursor is what a person uses
to say *which lane*, and a script has no cursor, so it has to say the one thing the
interactive session never had to ask. A bare lane name is refused rather than guessed
at: a lane name is unique inside its project and nowhere else.

There is no `where` action to print a lane's path for shell integration
(`cd "$(lane where)"`). The four-step day never needs it. Do not reintroduce
it as a shell-integration hook or a clipboard action — and note that `lane list
--json` is not that: it reports where lanes are, it does not move anybody's shell.

Actions: open a lane, list, settings, doctor.

There is no `changelog` action. It was one until the release notes became
generated from the merged pull requests rather than written by hand: keeping the
screen would have meant shipping a second copy of those notes inside the binary,
which is the duplication the whole release change exists to remove. What changed
in a release is on its GitHub release page. Do not reintroduce it — see
*Releasing* below. (**`docs/adr/0002-lane-listing.md`** predates this and still
lists the menu with `changelog` in it; it is a record of that decision, not the
current menu.)

**`enter` and `close` are not menu entries.** They are the two verbs the listing
offers for the row under the cursor — see **`docs/adr/0002-lane-listing.md`**
and *The lanes screen* below. Do not put them back as separate menu entries: both
used to begin by asking *which lane* from a picker showing the same names with none
of the status, which is a worse route to the same place. This is not the same thing
as hiding an entry behind an unmet prerequisite, which stays forbidden. Their
existence as *subcommands* is not a reversal of this: the reason they are not menu
entries is that the listing answers "which lane" better than a picker does, and that
reason has nothing to say about a caller with no screen at all.

### The listing's entry is `list`, in both places

It was `lanes`. The menu entry, the subcommand and every mention in the docs are now
one word, and the rename is not an alias: `lanes` is gone.

This is in tension with §4 of `docs/CONVENTIONS.md` — *a noun for a destination, a
verb for an action* — which `lanes` satisfied and `list` does not. Resolved, rather
than left looking like a violation:

- **§14 outranks §4 here.** One term per concept is the stronger rule, because two
  names for one screen is a fault a reader meets every time, while a verb-shaped
  destination is a fault they meet once. The subcommand has to be `list`: it is what
  `git`, `gh`, `docker` and `kubectl` all call it, and `lane lanes` reads as a typo.
  Having settled that, the menu either matches it or the tool calls one screen two
  things.
- **`open` was already the precedent**, and it is the strongest argument here: it is a
  verb, it is a menu entry, and it takes you to a screen. Nobody has ever found that
  confusing.
- The **screen** is still "the lanes table" or "the listing" in prose, and the
  `lanes_root` setting is untouched. What renamed is the entry you choose, not the
  thing it shows you.

### Machine-readable output: `--json`, on every subcommand

This file used to say there was none — "no JSON, no parseable listings, no careful
stdout/stderr split". That went with the premise above and goes with it.

- **`--json` exists on every subcommand**, before or after it (`lane --json list`,
  `lane list --json`), modelled on `gh`'s own convention since agent integration is a
  named goal here rather than an afterthought.
- **With `--json`, stdout is one JSON document and nothing else.** Not "mostly JSON":
  `lane list --json | jq` has to work every time, so everything lane would otherwise
  say — a spinner, a `✓`, a refusal, and any prompt it still has to draw — moves to
  **stderr**. It is moved, never suppressed: a script that cannot see why something
  was refused is worse off than one that has to redirect. The mechanism is one
  constructor argument (`ConsoleUi(to_stderr=True)`), not a flag checked in twenty
  places.
- **The fields are additive-only.** A field is added, never removed, never renamed,
  and never changed in meaning — clig.dev's rule, and the only promise that makes the
  output worth parsing. If a field turns out to be wrong, add the right one beside it.
- **`lane list --json` waits for `gh`, and that is not a breach of *the listing never
  blocks on `gh`*.** That rule is about the first paint; there is no paint here. The
  screen still fills the `pr` column in behind itself, because the screen still has a
  reader looking at it.
- Doctor's JSON carries a `status` per check **and** a small `facts` object per check.
  The prose may be reworded; the facts are the part a script reads, and they are the
  part the additive-only promise is about.
- **A field is never a glyph.** `lane list`'s `pr` cell says `—` and `checking…`,
  which are right on a screen and useless in a pipe, so the JSON carries
  `{"state": "not-applicable" | "open" | "merged" | "closed" | "none" | "unknown",
  "number", "url"}` instead. The rule generalises: if a value only makes sense to
  somebody looking at it, it is presentation, and the machine-readable form needs the
  fact underneath it.
- **Without `--json` nothing moves.** lane's own prose is the output of the command, so
  it stays on stdout exactly as it always has; only the usage errors the command line
  itself produces go to stderr in both modes.

### Missing input is TTY-gated, and lane never waits for an answer nothing can give

The old rule was *lane requires a TTY, full stop*. The new one is narrower and is the
same principle applied to a caller that has half the answers already:

- A subcommand **given every flag it needs runs with no prompt**, anywhere.
- Missing something, **with a terminal**: it asks, exactly as the session would —
  same wording, same validation, same re-ask loop. It is the real `Ui`, reached
  through the same seam.
- Missing something, **with no terminal**: it refuses, naming the question and the
  flag that would have answered it, and exits `3`. **It never blocks on stdin.**
- A **bare `lane`** still requires a terminal, unchanged, and still refuses with the
  same message. There is no half-working non-interactive menu.
- `--version` and `--help` are answered before any prerequisite is consulted and work
  anywhere, including CI.

Two consequences worth stating because they are easy to get wrong:

- **A flag value that names nothing on the screen is refused, not re-asked.** The user
  said which project they meant; quietly prompting would be answering a different
  question from the one they asked.
- **A supplied answer is spent when it is used.** Several prompts re-ask when an
  answer will not do — a branch name git rejects, a lane name already taken. Replaying
  the same flag into the same prompt would loop for ever, so the second time round
  says the value was not accepted.

**`--launch-editor` is opt-in from the command line, and only from there.** A script or
an agent has no use for a GUI window appearing on somebody's screen. The session still
launches the editor by default, because a person entering a lane is on their way to it
— that is what entering a lane *is*.

**Entering a lane with an unanswered ignored path, and no terminal, refuses** — before
applying anything, naming where the answer belongs. This is the one place the gate had
a real choice, so the reasoning is recorded: bringing the path in silently copies what
nobody asked for, and a `.env` is exactly the kind of path that turns up unanswered;
leaving it out silently exits `0` on a lane that is not ready, which is a lie a script
cannot detect. Refusing before the first step also keeps the command atomic and
re-runnable.

### Closing from the command line: row flags say what, `--yes` says do it

The close screen's rows are facts about *this* lane — whether anything would be
stranded, which branches it wandered through and left work on. So the flags cannot be
checked against a list written down anywhere: they are checked against the rows the
screen **would have drawn**, at the moment it would have drawn them, and a flag naming
something it does not offer is refused before anything is removed.

- **`--yes` accepts the screen**, taking the defaults it would have opened with: rescue
  what would be stranded, delete what goes anyway, keep what holds unique work.
- **Row flags change those defaults** — `--rescue`/`--no-rescue`,
  `--delete-branch`/`--keep-branch`, `--delete-others a,b`/`--keep-others`.
- **A row flag without `--yes` is a usage error.** Accepting a close is its own
  decision and no amount of detail about the rows amounts to having taken it. The
  alternative — pre-answering the rows and still drawing the screen — reads well until
  you are in a pipe, where the screen cannot be drawn and the same flags would then
  have to mean something else. One meaning each.
- **`lane close <lane>` with neither** shows the screen where there is a terminal, and
  refuses naming `--yes` where there is not.

Which flags must name a row, and which may name nothing, is not arbitrary: **a flag
asking for what closing already does is redundant where there is no row; a flag asking
to deviate needs something to deviate from.** So `--delete-branch` is accepted silently
when the branch goes anyway (deleting every branch it can is what closing *is*), while
`--keep-branch` is refused; `--delete-others` must name a row, because it names
specific branches and a name that is not there is a typo or a stale assumption; and
`--rescue` must have a row either way, because rescue exists to keep something, and
asking to keep what is not at risk means the lane is not the one the caller thinks.

### Exit codes — a public interface

A script branches on these, so they are a documented table, and **an existing code is
never renumbered**.

| Code | Name | Means |
|---|---|---|
| 0 | `EXIT_OK` | it did what was asked |
| 1 | `EXIT_REFUSED` | lane ran, and would not or could not: a close `gh` cannot verify, a worktree git would not create, a preparation step that failed, an unreadable config |
| 2 | `EXIT_USAGE` | the command line itself is wrong: unknown, contradictory, or inapplicable flags |
| 3 | `EXIT_NO_TTY` | an answer is needed and there is no terminal to ask in |
| 4 | `EXIT_NOT_FOUND` | a named project, lane or branch does not exist |
| 130 | `EXIT_INTERRUPTED` | what a shell reports for a process killed by SIGINT |

`3` is the old "lane is interactive and this is not a terminal" code, widened to
"an answer is needed and cannot be asked for" — the same fact about the same
situation, which is why it kept its number rather than being retired beside a new one.

### `--help` is generated, and is no longer written by hand

It was a hand-written paragraph, deliberately, and the reasoning was sound: there were
two flags, and the useful half of the text was the sentence explaining that there was
nothing else to type. That reasoning does not survive five subcommands with their own
flags each — a hand-maintained list of them is exactly the kind of prose that drifts
from the code and is never noticed. `argparse` (still stdlib; **Typer and Click are
still refused**) generates both `lane --help` and `lane <command> --help` from the one
definition that also parses them, and the tests assert against `parser.format_help()`
itself rather than against a second string kept beside it.

One thing this gave up, and it is worth naming: argparse's own wording now reaches the
user on a bad flag (`unrecognized arguments: --wat`) where lane used to answer in its
own prose. With five subcommands argparse's wording is the *consistent* one, and what
still matters — that a refusal says nothing at all on stdout — is asserted.

Consequences that are load-bearing:

- The menu is generated from **one table**, so it cannot drift from what the app
  can actually do. The menu is always the full list: prerequisites are enforced
  where they are used, never by hiding or greying out entries.
- Long-running steps (fetching origin, asking GitHub about a pull request,
  removing a worktree) show that something is happening — **including the ones
  after the last question**, which are the slowest a close has.

### Going back is visible, not a key you have to know

Every prompt that offers choices ends with a **`← Back`** entry, appended by the
`Ui` layer so no action can forget it. The main menu ends with `quit`. That is the
whole mechanism, and it is why almost nothing needs binding:

| Key | Everywhere |
|---|---|
| `↑` `↓` `Home` `End` | move |
| `Enter` | choose, or accept what you typed |
| `y` / `n` | answer a yes/no question |
| `Ctrl-C` | quit lane |
| `Space` | answer the row under the cursor — **the checklist widget only** |
| any printable key | narrow the list to what matches — **the three list screens** |
| `Backspace` | take the last character of that back |

**That table is the whole vocabulary**, and the last three rows are the only additions any
screen has ever been allowed to make. Each was taken deliberately rather than slipped in.

**Typing filters, on `choose`, `browse` and `check` alike** (`ui/filtering.py`), and it is
one implementation used by all three for the same reason the picker, the table and the
checklist already share as much as they do — three screens that merely resemble each other
drift. It needed no new key, and that is the test it had to pass:

- **Nothing printable was bound in any of the three.** `y`/`n` exist only in `confirm`,
  `Space` only in `check`. So a letter cannot collide with anything already there, which
  is exactly the argument `Space` had to make below before it was allowed to exist.
- **`Space` is not a filter character anywhere**, including the two screens where it is
  unbound. It already means *answer this row* on one of the three, and a key meaning one
  thing on one list screen and another on the next is what the closed vocabulary exists to
  prevent. A filter is therefore one word, which is what a filter over paths, lane names
  and branch names is anyway.
- **`Backspace` takes a character back and there is no key that clears the filter.**
  Backspacing to empty is the text editing `Ui.text` already relies on, reused rather than
  invented.
- **It is never a mode.** What was typed is on screen, immediately under the title —
  `<n> of <total> · filter: <text>` — and where it matches nothing the screen says
  `No matches for '<filter>'.` in one line rather than freezing with an empty frame
  (docs/CONVENTIONS.md §12). The corner says `type to filter` on all three.

**`Space`** belongs to `ui/checklist.py` — every screen whose rows carry their own answer,
which is now two of them: which ignored paths come into a lane, and what closing a lane
does. **The second one added no key**, and that is the test the first one was spending its
budget against. It was taken deliberately rather than slipped in:

- `Space` toggling a multi-select is not this tool's invention — it is what every other
  multi-select in a terminal does — and it is what makes a dozen answers cost a dozen
  keystrokes instead of a dozen round trips into a sub-screen. On a **folder** row it
  answers every path beneath it at once, which is what stops two hundred ignored paths
  being two hundred keystrokes.
- **`Enter` there does to a row exactly what that row *is*, and nothing else.** It opens
  a folder — `Enter` doing what it does in the lanes table — leaves the level from
  `← Back`, accepts from `apply`, abandons from `discard`, and on a **leaf** it does
  nothing at all, because a leaf's answer is `Space`'s job and there is nothing to open.
  So `Enter` never means "accept" on this screen either: accepting is a row, exactly as
  going back is. That is the reason `Space` had to exist in the first place — the screen
  before this one cycled the row with `Enter` and then had no key left to finish with, so
  it grew a `continue` row to stand in for one.
- **What it replaced, and why it was wrong.** `Enter` used to open the row if it opened
  and otherwise accept the level you were standing in — root being the screen, inside a
  folder being that folder. Two faults, both from the same fallthrough: on a **leaf** at
  any depth it fell through to *leave the level*, so a press on a file walked you up out
  of the folder you were reading; and the accept was reachable only from a **root-level
  leaf**, which a repository whose ignored paths all sit under folders does not have —
  a screen with no way to finish at all.
- The checklist's footer names which of `open` / `go up` / `apply` / `discard` applies to
  the row under the cursor, and names **none** on a leaf, because naming a key that does
  nothing teaches a lie. The lanes table's footer names nothing beyond the shared set,
  because it adds no key and `Enter` there always means the same thing. **Both come out of
  one renderer** — `ui/footer.py`, bottom-right and dim, which every widget calls with the
  keys it actually has (docs/CONVENTIONS.md §3a).

One widget, one key. **A new screen still introduces none.** What Ctrl-C does, at a
prompt and while lane is **working**, is below, under *Ctrl-C quits lane*. A letter key for "close" was considered and
rejected: a footer legend would make it discoverable, but it would still be this
tool's invention. Choosing a row opens a two-entry menu instead — one keystroke
more, no new vocabulary. If a future change wants letter keys, that is a decision
to take deliberately, not a convenience to slip in.

**Escape is deliberately not bound.** Two attempts failed, and both are recorded so
nobody tries them again:

1. `eager=True` — fires on the Escape half of Option+Left (which arrives as *Escape
   then Left*), abandoning the prompt and making word movement impossible.
2. Bound normally plus `(escape, Any)` to swallow sequences — a lone Escape is then
   ambiguous with every escape *sequence*, so `prompt_toolkit` waits. Measured
   against the built binary: **1.6 seconds** before anything happened, which reads
   as "Esc does not work". Lowering `ttimeoutlen` does not fix it; the wait is
   binding-level (`timeoutlen`), not only the parser.

Leaving it unbound costs nothing now that Back is visible, and has a bonus: nothing
of ours can trip over Option+Arrow, so `prompt_toolkit`'s own word movement works
untouched in the text prompt.

**There is no `q`, no vim keys (`j`/`k`), no digit shortcuts.** If a key is not one
a user would already expect from any other terminal program, it does not belong.

**Backing out is announced by saying nothing.** Every other tool just shows the
menu again; lane does not print an explanatory message on the way back.

**The terminal cursor is hidden in prompts** (`show_cursor=False` on the
`FormattedTextControl`). Without it the cursor parks on the first character of the
prompt, and that letter reads as though it were selected.

Abandoning never leaves half-finished work, and that is guaranteed
**structurally, not by rollback logic**: every question an action asks comes
before its first irreversible step. Opening a lane asks everything — project,
description, mode, branch — and only then creates the worktree. Closing a lane
runs its checks, shows what it found, asks for confirmation, and only then removes
anything. So abandoning any prompt is always a clean no-op. Keep it that way: if
you find yourself wanting rollback logic, the questions are in the wrong place.

**Preparation is the one place worth reading that rule carefully.** It asks its
questions before it writes its first file, so backing out of its screen changes
nothing — but reached from `open`, the worktree already exists, because `open` ends by
entering the lane it just made. That is not a breach: **abandoning preparation leaves a
complete lane that is merely unprepared**, which the listing describes, the close flow
can act on, and the next enter repairs. The rule is about half-finished work, and there
is none.

### Ctrl-C quits lane, from anywhere, and the only variation is *when*

**Ctrl-C exits the process.** At a prompt, at any depth of any screen, during a spinner,
in the middle of a step — one gesture, one outcome, and it leaves by the same door `quit`
does, farewell included. Two lines of evidence put it here rather than at "back out":

- **What lane's own code already assumes.** Going back is a **visible row** everywhere in
  this application — `← Back`, the checklist's `discard`, the listing's `← Back to the
  menu`, the menu's `quit`. Ctrl-C was standing in for a job lane had already solved
  another way, and a key that duplicates a visible row is a key with nothing left to do.
- **What comparable tools do.** One-shot wizards (`npm init`, `gh`'s survey prompts) treat
  Ctrl-C as "abort the whole thing" because they have no navigation model to back up
  through. Persistent, multi-screen tools closer to lane's shape — `k9s`, `lazygit` —
  bind it to "quit the application", unconditionally, and move between their own views
  with an entirely different key. lane is structurally the second kind: a menu loop you
  return to, not a single wizard.

**Nothing lane does may end in a traceback** — that is still the one outcome a user can
do nothing with, and `cli.main` is the backstop under all of it. What differs between
situations is only what is *said* on the way out, and whether the exit waits:

1. **At a prompt, or while a spinner is up before anything irreversible** — fetching
   origin, asking GitHub, reading lane status, any screen at any depth. Nothing was under
   way, so nothing is said: farewell, and out. The widgets raise `Quit`; `ConsoleUi.progress`
   turns a `KeyboardInterrupt` into the same thing, because a Zone 1 spinner is as clean
   as a prompt.
2. **During a close's removal phase** — the one stretch where stopping half-way is worse
   than either finishing or never starting. A partly deleted working copy, or a lane whose
   worktree is gone but whose branch and metadata survive, is a state nothing in lane can
   describe, let alone repair. So the interrupt is **deferred** (`lane.interrupts`):
   acknowledged on screen the moment it lands, raised once the phase is done — and then
   lane exits, rather than reporting it and showing the menu again. A second Ctrl-C is
   never deferred: it means *now*, and the acknowledgement says so. This needs
   `start_new_session` on git subprocesses to mean anything (see *The git backend*).
3. **Anywhere else** — it landed while a step was actually running, so unlike the first
   case it is *not* guaranteed to be a clean no-op. lane says so in one line, names
   `lanes` as the screen that shows where things stand, and *then* exits.

The two exceptions carry that difference: **`Quit`** is Ctrl-C at a prompt or a Zone 1
spinner, and exits silently; **`KeyboardInterrupt`** is one that landed while lane was
working, and exits after saying what may be half-done. `session.run` is where both are
turned into the same farewell and the same exit code, and it is the only place either is
caught. `cli.main` still answers `130` for an interrupt that escapes the session entirely
— a lane that did not get to close its own road is a different fact from one that did.

**`Abandoned` is not one of these** and must not be folded into them. It is what a
**visible row** raises — `← Back`, the checklist's `discard` — and it returns to the
screen above, silently, exactly as it always has. A row that says *back* has to go back
rather than out.

Zone 2 is the **only** place an interrupt is deferred, and it is deferred because its
questions are all behind it — not as licence to defer one elsewhere. If a new step wants
deferral, check first whether it is really asking for its questions to be moved earlier.

**Preparation is Zone 1, and it was a deliberate decision rather than a default.** Its
questions are behind it too, which is the shape Zone 2 has — but two things put it back
in Zone 1. Every clone is written to a staged path beside its target and renamed into
place, so **no step can leave a half-populated path**: there is nothing whose half-done
state lane could not describe. And a `run` step can be a two-minute install, so
deferring would leave Ctrl-C apparently doing nothing for two minutes, which is the very
perception Zone 2's acknowledgement exists to prevent. It does, however, borrow one
thing from Zone 3: it **says** what it was doing, because earlier steps completed and
are real work, so Zone 1's silence would be a lie.

**One cost of this, named rather than left to be discovered.** `text` and `confirm` have
no visible row to go back with — there is nothing to choose between — so Ctrl-C was their
only way out, and it is now a way *out of lane*. A mistyped answer at a text prompt is
answered by finishing it and correcting from the screen that follows, not by backing out
of it. If that turns out to bite, the fix is to give those two prompts a visible way back,
not to give Ctrl-C a second meaning.

## The lanes screen

One screen, and the list is the interactive thing. A cursor moves over the rows;
whatever happens next happens to the row under it. Full reasoning in
**`docs/adr/0002-lane-listing.md`**; what must not regress:

- **Looking and acting are the same widget.** There is no table followed by a
  second prompt re-listing the lanes.
- **The screen answers two questions**: *what am I in the middle of*, and *which of
  these can I close, and what is stopping the ones that cannot*. The second is what
  shapes the layout. Columns are `lane`, `state`, `pr`, `age`; `state` and `pr` are
  never dropped and never truncated, and `age` is the only one that may go.
- **`branch` has no column.** It was the lane name with a prefix in front of it,
  spending forty columns to repeat the first column. It is in the panel. What was
  load-bearing about it — *is this detached*, which changes what closing does — is
  a state, and lives in `state`.
- **A panel under the table follows the cursor** and shows only what the status
  pass already collected: the branch, the description when the lane name could not
  keep all of it, and one sentence about the pull request — which carries the whole
  history when there is one (`PR #42 open — <url> · earlier: #41 merged`), because
  `MAX_DETAIL_LINES` is three and a line per pull request would be sliced off, losing
  exactly what it is there to show. **It never makes a git
  or `gh` call of its own.** That rule is what stops it becoming the close flow's
  diagnosis printed twice; which files are dirty and which commits are unpushed
  cost a call per lane and stay in the close flow, where they change a decision.
- **The order never changes while the screen is up** — project, then name.
  Rows that rearrange themselves under a cursor are unusable.
- **The description is only shown when the name could not keep it.** A lane's name
  *is* its description slugified, so printing both was one string twice. It earns a
  line when the forty-character cap cut it short, or transliteration replaced
  letters the user typed (`Login sayfası hatası`).
- **Pull request state never holds up the first paint.** Git status is local and
  fast and is collected before the screen appears; `gh` is **two** processes per lane
  and is not, so the `pr` column opens as `checking…` and fills in behind the screen
  you are already using. If the listing blocks on a `gh` round trip, this is broken.
  The number is the thing to hold the line on, not the fact that it is more than one:
  both calls are in the fill, and any further question must go there too.
- **What is stacked on the branch lives in `state`, not `pr`.** `pr` is the lane's own
  pull requests; a review based on its branch is somebody else's, and putting it there
  would conflate whose work is whose. It belongs in `state` because it changes what
  closing does — `↳ N stacked`, in the same vocabulary of counts and marks, and it
  makes the cell read as blocked, because it is. The panel names the numbers
  (`base of #99`) so they can be looked up.
- **`state` reads the pull request answer, so it settles alongside it.** A squash or
  rebase merge leaves the lane's commits nowhere in the base, so the ancestry check
  reports `not merged yet` about work that plainly landed — directly beside a `pr`
  cell reading `merged`, about the same lane. `state` therefore counts a `MERGED`
  pull request as having reached the base, which is the rule the close flow has
  always applied. Two consequences to keep: the merged verdict **is not final until
  `pr` has filled in**, so `state` must be drawn from the row on each repaint and
  never computed once before the fill; and **fetching does not fix this** — it was
  measured on the maintainer's own repository, where the squash commit was already
  local and the lane's commits were simply gone. A fetch in the listing would buy a
  network round trip before every first paint and leave the contradiction standing.
- **`state` never prints `↑ N unpushed` beside `✓ merged` either.** The same false
  negative reaches the count next door: merging with *delete branch* removes
  `origin/<branch>`, so there is no upstream left to measure against and the count
  falls back to the base — where the squash left none of the lane's commits. It is
  then describing work that landed. Suppressed only when there is no upstream *and*
  the pull request merged *and* nothing was committed after it; a live upstream, an
  open pull request, or a count that could not be established all leave it standing.
- **`unknown` and `none` are different answers.** `none` means GitHub was asked and
  said no; `unknown` means it could not be asked, and the panel names the command
  that fixes it. This is the one thing the close flow can never tell you, because
  for such a lane it refuses before it gets that far.
- **After closing you stay in the listing**, one row shorter, with the cursor on
  the row that took the closed one's place; pull request answers already paid for
  are kept, so the second paint is immediate. **After entering a lane you go back to
  the menu** — your attention has moved to the editor, and the listing's data is
  about to go stale. The asymmetry is deliberate: closing repeats, entering does not.
  **Backing out of preparation is the exception**: it lands back at the table, because
  nothing happened and the editor never opened.
- **Zero lanes renders no table.** It says so in one line and returns.

## `gh` is a settled dependency

`gh` (GitHub CLI) is required, installed and authenticated. **This is decided —
do not revisit it.** The reasoning: there is no official GitHub SDK for Python.
GitHub's own Octokit libraries cover JavaScript, Ruby, .NET and Terraform only, and
every Python option is third-party. Taking one on would mean owning token storage,
device flows and keychain handling for the sake of a single API call. `gh` has
already solved that.

- **Enforced where it is used, not at startup.** Closing a lane is the only thing
  that needs `gh`, and only for lanes that actually have a GitHub remote and a
  branch. If such a lane cannot be checked because `gh` is missing or logged out,
  that close is refused with exactly how to fix it (`brew install gh`,
  `gh auth login`). Everything else — including closing a lane whose remote is not
  GitHub — carries on unaffected. Doctor reports the state up front so it is never
  a surprise.
- The interaction sits behind a small `GitHubClient` interface with a single real
  question: **what pull requests has this branch had?** — plural, because a branch
  carries a history of them and answering with only the most recent silently drops
  the rest. Its answer includes "I cannot tell you, because `gh` is missing or
  logged out" as a first-class result. The close path decides from that answer alone
  and **never probes the environment separately**. Today it shells out to
  `gh pr list --head <branch> --state all --json number,state,url,headRefOid`;
  tomorrow it might be an HTTP call, and the rest of the application must not be
  able to tell.
- **A second question, and so two `gh` subprocesses per lane** — `what is based on
  this branch`, via `gh pr list --base <branch> --state open`. It was one, and the
  count is worth stating rather than leaving to be counted: `--head` and `--base` are
  opposite ends of one relationship and only the second reveals that closing the lane
  would delete the base of somebody's open pull request. Only open ones are asked
  about; a closed or merged one is no longer at risk. Its answer is `Dependents`,
  where **empty means GitHub was asked** and `CannotTell` means it could not be — the
  two must never collapse, because one is permission to delete the branch and the
  other is not. What the count does *not* buy is any delay before the first paint:
  both calls happen in the fill, and a third question would have to earn its place
  the same way.
- **One of them is decisive, and the model says which** — `Found.decisive` is the
  open one if there is one, whatever its age, else the newest merged, else the
  newest; `Found.landed` is `decisive` being `MERGED`. Deliberately *not* "any of
  them merged": with a follow-up still open the lane holds work that has not landed,
  and the squash-merge correction would then excuse commits nothing has taken.
  Callers read these rather than re-deriving the rule.
- The check does not apply to non-GitHub remotes or to lanes on a detached HEAD:
  there is no pull request to ask about, so those closes proceed on git's own
  evidence and never touch `gh`.
- A `MERGED` pull request **counts as clean even when git's ancestry check
  disagrees**: a squash or rebase merge leaves the lane's commits nowhere in the
  default branch, and resolving that false negative is the entire reason this
  feature exists. `OPEN` and `CLOSED` are blocking issues, each reported with its
  URL; "no pull request found" is a blocking issue without one. **An open pull
  request blocks even when an earlier one merged** — it is work that has not landed,
  and closing the lane takes the branch it lives on. The earlier one is still
  reported, in its own quiet tone: a `✓` beside a pull request that was closed
  without merging would be wrong, and a `!` would invent a blocker out of history.
- **An open pull request based on the lane's branch blocks the close.** Closing
  deletes the branch, and deleting a base breaks the pull request built on it. Nothing
  about the lane's own work can reveal this: its pull request can be merged and its
  tree clean and the close would still take out an open review. Whose work is at stake
  is the only difference, and it changes nothing about whether it is at stake. **A
  dependents question that cannot be answered refuses the close**, exactly as the
  lane's own does — "I could not ask what is built on this" is not permission to
  delete it.
- **A merged pull request is not an amnesty for everything on the branch.** What it
  carried is safe; what was committed afterwards exists in that worktree and nowhere
  else. The two are told apart by counting from `headRefOid`, the commit its head was
  at — the only way, since a squash merge leaves ancestry unable to separate them. If
  that commit is no longer on the branch (amended or rebased since), the count is
  **unknowable and the close is refused**, exactly as it is for an unreachable `gh`.
  Never conflate "cannot tell" with zero.
- `gh` is **not bundled** into the binary. It is an external prerequisite,
  documented in the README.

## The git backend — decided: subprocess against the `git` CLI

**`git` is therefore a runtime prerequisite**, checked **at startup** rather than
per action, because without it nothing lane does works. The session refuses with a
message naming what is missing. That refusal has the same two exemptions as
everything else: `--version` and `--help` are answered before any prerequisite is
consulted, and **doctor is always reachable**. Doctor is the thing that explains a
missing prerequisite, so it can never sit behind one; when git is absent the
session starts, offers doctor, and refuses everything else.

Full evidence in **`docs/adr/0001-git-backend.md`**. The short version, so nobody
re-opens this without reading it:

- **A library (pygit2, dulwich, GitPython) cannot do the job cleanly.** Between the
  three, one or more of: no detached worktree support, no worktree removal API,
  discards uncommitted work on removal where git refuses, cannot authenticate the
  way this machine already does (SSH agent, `osxkeychain`), or fails to bundle
  under PyInstaller one-file. None of the failures is close; see the ADR for the
  evidence.
- **A hybrid (library for inspection, `git` CLI for the worktree lifecycle) was
  rejected on evidence, not taste**: it means two independent git implementations
  reading the same repositories, so disagreement between them becomes a bug class
  the single-backend design cannot have. The performance argument does not survive
  measurement — 12 lanes × 4 git calls is 161 ms across a thread pool.

What this buys, and what must not be given away casually: **git enforces its own
safety rules, so lane inherits them instead of reimplementing them** —
`worktree remove` refuses a dirty tree, `branch -d` refuses an unmerged branch.
Both are exactly the checks lane asks the user to override deliberately, and both
stay git's to make. And **authentication is whatever the user already configured**,
with no credential handling in lane at all — the same reasoning that settled `gh`,
applied to git.

Rules for the implementation:

- Parse only **stable, machine-oriented output** — `--porcelain`,
  `rev-list --count`, `show-ref --verify --quiet`, `--abbrev-ref`,
  `merge-base --is-ancestor` (exit code only). Never human-readable or localised
  output. The backend pins the environment (`LC_ALL=C` and friends) so a user's
  config cannot change what it reads.
- The listing collects per-lane status across a **thread pool** — subprocesses
  release the GIL, and this is what keeps the listing fast (measured 5.0× speedup).
- Every git process is started with **`start_new_session=True`**, so it is not in
  the terminal's foreground process group and Ctrl-C reaches lane and nothing else.
  Without it, deferring the interrupt during a removal buys nothing: the terminal
  would kill git half-way regardless of what lane did with its own copy of the
  signal. lane still owns the child's lifetime — an interrupt it does *not* defer
  unwinds `subprocess.run`, which kills the child on the way out.
- **Default-branch detection**: `origin/HEAD` first, then
  `git remote set-head origin --auto`, then the `main`/`master`/`develop` probe as
  a genuine last resort — and if all of that fails, **say so rather than guessing
  `main`**.

## The four seams

The application reaches the outside world through four interfaces. Three are faked
in tests; the fourth is not. **Everything not listed here — the filesystem above
all — runs for real.**

| Seam | What it is | Faked in tests? |
|---|---|---|
| `GitBackend` | all git access (subprocess to `git`) — including what a lane is missing | **No.** Real backend, temporary repositories |
| `GitHubClient` | pull request state | Yes — the suite never authenticates or touches the network |
| `Environment` | TTY-ness, tool presence on PATH, launching the editor | Yes — this is what lets the suite run under pytest without a TTY and without opening an editor |
| The prompt layer (`Ui`) | everything that asks the user something, and everything it tells them | Yes — replays scripted answers, records what was said |

**There are three implementations of `Ui`, and the third is production code.**
`ConsoleUi` asks a terminal, `FakeUi` replays a script in tests, and
`cli.answers.Prefilled` answers from the command line and falls through to a real one
for whatever the flags did not cover. Every asking method therefore takes a `key` —
a name for the question, which the two real implementations ignore — because a flag
has to find its prompt, and finding it by the prompt's *title* would make a §8
rewording silently re-route a flag.

`GitBackend` exists so the implementation can be **swapped**, not so tests can
avoid git. Tests use the real one against temporary repositories.

**`prepare/apply.py` is not a fifth seam.** It clones, links, runs a configured command
and measures a path — the only place any of those happens — and it is exercised for real,
because the filesystem is real in tests and `true`/`touch` are honest commands. A fake
would get exactly the things wrong that matter: whether a clone shared blocks, whether a
symlink was followed, whether a swap left a partial tree. `Environment` keeps the editor
launch because that is fire-and-forget and must never happen under pytest; a prepared
command is waited on and its exit code read, which is a different shape.

`Environment` reports tool presence **for doctor's benefit**; it does not decide
whether a close may proceed — that comes from `GitHubClient`'s answer. The TTY
refusal is tested by faking `Environment`, never by manipulating the real terminal.

The seam is called **`Ui`** and it both asks and tells. Output belongs with asking
rather than in a fifth injected thing: both are presentation, an action needs both,
and the progress indication for a long step ("Fetching origin…") is telling. So
`Ui` carries `choose`/`text`/`confirm`/`browse`/`check` alongside `info`/`ok`/`warn`/
`error`/`detail`/`heading`/`blank`/`progress`.

**There are three screen shapes and they answer different kinds of question.** `choose`
asks one question. `browse` is a screen the user stands in and acts on one row of.
**`check` is a screen where every row carries its own answer** — which ignored
paths come into a lane, and what closing a lane does — so it is a decision over a *set*
rather than a question with an answer, and it returns every **leaf** that was answered,
and which way, when the screen was accepted. It takes the same columns `browse` does and a `rows` callable returning a **tree**
of them, one level per screen, plus what arrives already answered and an optional `summary`
for the running count. A leaf has three answers — in, out, and *not yet answered*, which is
an **absent key** rather than a value; a folder stands for everything under it and so has
five, adding *partly unanswered* (`?`) to the mix (`◐`). Every level ends with two rows — the way on and the
way out — and every level inside a folder has a `← Back` above them; the root has no
`← Back`, because there is nothing above it. **What those two rows are called is the
caller's** (`Finish`): `apply`/`discard` for a screen of ignored paths, `close`/`leave
open` for the close, because what accepting a screen *does* differs, and one vocabulary
describing two things is how a word stops meaning either. The shape never varies — rows,
on every level, never a key.

**`browse` is a screen the user stands in, not a question they are asked** — that
is the whole difference between it and `choose`. It takes columns and a *callable*
returning rows (the action owns the data and any locking; the widget owns the
drawing) and returns the row under the cursor plus its index, so an action can put
the cursor back where the user left it. It also takes a `fill`, which the UI runs:
the real one on a thread wired to a repaint, the fake straight through. That
asymmetry is deliberate and is the only reason "render what is known, fill the rest
in" can be asserted without sleeps.

Widening the seam is allowed; bypassing it is not. An action never imports
`prompt_toolkit` or `rich`.

**Abandonment is an exception (`Abandoned`), not a return value.** `session.py`
catches it and returns to the menu. Threading a sentinel through every call site
would make it possible to forget one, and forgetting one is exactly how a
half-finished action would come about. The exception cannot fall through to the
next statement, which makes the invariant structural rather than a matter of care.

**Two actions catch it, and only two.** The listing catches `Abandoned` — around the
per-row verb menu, around the close it launches, and around the enter it launches — so
that backing out of any of them returns to the table rather than to the main menu; the
table is a screen you are standing in. All three are safe for exactly the same reason as
everywhere else: every question still comes before the first irreversible step, so an
abandoned verb menu, close or preparation has changed nothing. Preparation is included
because it *is* a screen, and its `discard` row is an `Abandoned` like any other — so
discarding it lands back on the table you started from rather than at the main menu. Do
not take this as licence elsewhere; if another action wants it, it wants a screen.

It catches `Abandoned` and **only** `Abandoned`. `Quit` and `KeyboardInterrupt` pass
straight through to the session, because they are not backing out of anything — see
*Ctrl-C quits lane*.

**Preparation catches the interrupt too, for one line and then re-raises.** It is the
only step in lane that does several independent pieces of work in sequence *after* the
last question, so it is the only one where Zone 1's silence would be a lie — it names the
step the interrupt struck, says entering again finishes the job, and lets the `Quit` carry
on to the session, which exits. It never swallows one.

The prompt layer is **an interface the action calls, not a library it imports**.
Actions never touch `prompt_toolkit`; they ask through this seam and get an answer
or an abandonment back. Most questions can be gathered before an action starts and
where that is possible it is preferable — but some genuinely cannot (closing a
lane only knows what to confirm after it has fetched and run its checks), so the
interface is **passed into the action** rather than the action being handed a
finished set of answers. The rule that matters: the action does not know how the
asking happens.

The picker widget itself sits **below** this seam: a component with its own tests,
driven through `prompt_toolkit`'s pipe input, which is how auto-selecting a lone
candidate and re-prompting on bad input get covered without a terminal.
Session-level tests replace the whole seam and never reach it.

**The lanes table and the checklist are the same kind of component and get the same
treatment** — `ui/table.py` and `ui/checklist.py`, below the seam, with
`tests/test_table.py` and `tests/test_checklist.py` driving them through pipe
input. The checklist reuses the table's layout (`fit`, `clip`, `window`, `vertical`,
`row_fragments`) rather than growing a second one, and adds a two-character mark gutter in
front of every row for the answer. **The drill-down is the widget's, not the action's**:
`Walk` holds which level is on screen and where the cursor was parked on the way into
each, so the seam is called once for the whole tree. Threading "now descend into this
one" back out through the action would put the widget's own state in the caller's hands,
which is the shape `Abandoned` exists to avoid. Its layout is a pure `paint(…, width, height)` returning the lines it would
draw, which is how narrow terminals, scrolling and the panel are asserted without
one. Session-level tests replace the seam whole and never reach it: a script drives
"select the second lane, close it" as `FakeUi([1, "close", True])`, matching a row
by position or by any of its cell texts.

## The prompt layer

`fzf` is not a dependency — the picker is an in-process `prompt_toolkit` widget.
No external binary, and no "install fzf for a better experience" branch.

**Decision: `prompt_toolkit` directly, not `questionary`.** Rejected because of the
key handling, which is a stated requirement with precise semantics: `Esc` abandons
everywhere and `Ctrl-C` maps onto it inside a prompt. That is per-prompt-type key
binding plus a three-way distinction between *answered*, *abandoned* and
*interrupted*. `questionary` returns `None` for its cancellation cases and does not
cleanly separate them, so getting there would mean reaching through it to the
`prompt_toolkit` underneath — at which point the wrapper is only in the way. Using
`prompt_toolkit` directly means explicit `KeyBindings`, one dependency instead of
two, and `create_pipe_input()` + `DummyOutput()` for driving the picker headlessly
in tests.

**Rendering: `rich`**, for the non-prompt output — the listing, doctor, the close
summary. `prompt_toolkit` can print styled text, so this is a real choice rather
than a necessity; `rich` earns its place on the listing and doctor report, which
are tabular and would otherwise be hand-aligned. It is pure Python and bundles
without incident.

Both were verified to build and run under PyInstaller one-file (~12 MB, ~113 ms of
combined import cost).

**Decision: the checklist is lane's own table, not `prompt_toolkit`'s `CheckboxList`.**
`CheckboxList` is the obvious answer and does not survive the requirements: it draws every
option into one window with **no scrolling of its own** — the exact defect already measured
on `picker.pick`, where 300 branches became 304 lines with the cursor walking off the bottom
of the terminal, and forty loose ignored files in one folder is a real screen. It also has
no columns, no dim lead, no cursor panel, and no way to let a slow column land behind the
first paint. All four are things this screen needs and the table already has, so the
checklist is a widget beside `table.py` sharing its layout. **Do not bring in a second
prompt framework** (`InquirerPy`, `textual`) for one screen, and do not resurrect
`questionary` — rejected above, with reasons.

**A single candidate is auto-selected without prompting, and bad input re-prompts
instead of aborting.** In a windowed picker "re-prompts" means an unrecognised key
is ignored and the picker stays up — it never aborts.

**A yes/no question is a real `y`/`n` confirm, not a two-option picker.** Labelling
a prompt `[y/N]` and then refusing to accept `y` is worse than either option alone.

## Invariants — each with its reason

These must never regress. Each is one line of behaviour and one line of why.

- **lane leaks nothing into the projects it manages** — no `.lane.toml`, no marker file,
  no directory, ever. A project must not be able to tell lane exists, or lane stops being
  something you can drop on any repository and becomes something a repository has to
  adopt.
- **lane learns no package manager** — no `yarn`, `npm`, `go` or `cargo` anywhere in the
  source. The mechanism is generic and the project-specific knowledge is configuration,
  or the list of ecosystems is endless and always one short.
- **Entering a lane never overwrites what the lane changed.** Full stop, with no
  exception to remember: a path answered *in* that is already in the lane is left exactly
  as it is. A
  dependency tree the user patched by hand is work, and losing it silently is the one thing
  this feature could do that is worse than not existing. This used to carry "unless the
  user asked for that path to be refreshed", and dropping `refresh` is what let the rule
  become unconditional — which in turn let `prepare.needed` be the *only* function that
  decides what a step does, where two used to disagree on exactly this case.
- **A failed or interrupted preparation leaves a usable lane** — it lists, it closes, and
  entering it again finishes the job. Nothing about preparation is recorded per lane,
  which is what makes entering again the whole repair rather than a reset.
- **A clone is staged beside its target and renamed into place** — so no interrupt can
  leave a half-populated path, which is why preparation needs neither rollback logic nor a
  deferred interrupt to promise it.
- **Only paths git ignores *in the lane* are ever written** — asked of git in bulk, in
  both spellings. That is what keeps preparation out of the listing's `state` cell and out
  of the close flow's first check, and what stops a tracked file being overwritten.
- **A folder row is never a step for the folder** — it stands for the paths inside it and
  stores one step each. A partly ignored directory holds tracked work, so a step for the
  directory itself would overwrite it.
- **A leaf has three answers and a folder has five** — `✓` in, `✗` out, `○` not yet
  answered; a folder adds `?` for *something under here is still unanswered* and `◐` for
  *all answered and they disagree*. A folder is folded whatever its paths were answered,
  because the marks can say "some of these"; what it must never do is show a mark that is
  false for half of what it stands for. This replaced *"a folder is not folded unless its
  paths agree"*, which was the honest workaround for a mark with two states and which cost
  the screen its shape: a disagreement opened a folder out into a flat run of rows. The
  partition of the five is exhaustive and lives in exactly one function
  (`checklist.mark_for`), with a leaf as its degenerate case rather than a rule of its own.
- **A folder is a screen you go into, and one keystroke on it answers everything under
  it** — around two hundred ignored paths is a real repository, and choosing among two
  hundred flat rows is not a screen. The tree comes from grouping discovery's own answer
  on `/`; a level of fewer than three rows is drawn in its parent rather than behind a
  keystroke that offers no choice.
- **One component answers "which paths come into a lane", opened from both doors** —
  entering a lane and settings · preparation call the same `Ui.check` over the same
  `prepare.Sheet`. Two screens that merely resemble each other drift, and these two had:
  one toggled in place, the other made you enter the row, choose *change*, and pick a verb.
- **A lane's branch never tracks anything but itself** — a branch lane *creates*
  gets no upstream, because the only candidate would be `origin/<base>` and a bare
  `git push` would then land on the default branch; a branch lane *adopts* from the
  remote tracks `origin/<itself>`, which is what the user expects and what makes its
  unpushed count a real measurement rather than a fallback count against the base.
  This invariant used to read "new branches are created with no upstream", which
  named the mechanism rather than the hazard — and the hazard is tracking the
  **base**, not tracking at all. An adopted branch cannot reach the default branch,
  because it is not the default branch.
- **Commits on a detached HEAD are parked on `wip/<lane>` before removal, and that
  branch is never deleted** — deleting it would defeat the entire purpose of the
  rescue.
- **Branch naming is decided per lane, not globally** — one lane can be `bugfix/…`
  while the next is `feature/…`; it is a property of the task, not of the machine.
  **This is about the choice, not about the menu it is made from.** Which prefixes are
  offered *is* a setting (`branch_prefixes.toml`, settings · branch prefixes), because a
  team whose branches are `spike/` and `poc/` otherwise reached for `other…` every time —
  a free-text prompt standing in for a list lane could perfectly well have offered. Do not
  read this invariant as forbidding that, and do not let anything default, remember or
  infer the prefix *for* a lane.
- **Lane and branch names are always plain ASCII** — task descriptions are typed
  in whatever language the user thinks in; paths and refs must not be.
- **The config upgrade notice stays one short line** — what a release changed is
  on its GitHub release page, and an upgrade notice must not become a changelog
  dump.
- **Doctor is always reachable, no matter which prerequisite is missing** — it is
  the action that explains missing prerequisites.
- **The rest of the menu is never gated behind a missing `gh`** — only closing a
  GitHub-backed lane needs it.
- **A bare `lane` requires a TTY**, `--version` and `--help` excepted — there is no
  half-working non-interactive menu to maintain. A **subcommand** runs anywhere and
  refuses by name the moment it needs an answer no flag gave it; what it never does is
  wait on stdin for one.
- **A subcommand answers an action's questions; it never answers them itself** — one
  implementation of opening or closing a lane, reached by two callers. The moment a
  subcommand decides something for itself, the two entry points can disagree, which is
  the entire hazard the no-subcommands rule used to avoid by not having a second caller
  at all.
- **With `--json`, stdout carries one JSON document and nothing else** — everything
  lane says moves to stderr rather than being suppressed, because a script that cannot
  see a refusal is worse off than one that has to redirect.
- **A `--json` field is added, never removed, renamed or redefined** — it is the only
  promise that makes parsing the output worth doing.
- **An exit code is never renumbered** — it is a public interface a script branches on.
- **Going back is a visible entry, never only a key** — `← Back` in every choice
  prompt, a `← Back to the menu` row at the end of the lanes table, `quit` at the
  menu. A key a user has to be taught is a key that should not exist.
- **The editor launches from a session and not from a subcommand** — a script or an
  agent has no use for a GUI window appearing; a person entering a lane is on their way
  to one. `--launch-editor` asks for it back.
- **Looking at a lane and acting on it are the same widget** — a table you read
  followed by a prompt that re-lists the same lanes makes the reader match a row to
  an action by eye, and grows as lanes × verbs.
- **The lanes screen binds no key the picker does not** — arrows, `Enter`,
  `Ctrl-C`. A letter key for a verb would be this tool's invention, however visible
  the legend.
- **The table binds exactly the picker's keys** — a screen whose rows carry their own
  answer is a different widget, `checklist.py`, and that is where `Space` lives. Asserted on
  both binding tables themselves, because a bound handler that happens to do nothing still
  swallows the keystroke, which is not the same as leaving a key unbound.
- **The checklist binds the picker's keys plus `Space`, and nothing else ever** — and
  `Enter` there acts on the row under the cursor exactly as it does everywhere else in
  lane, which is why `apply` and `discard` are **rows** rather than a key or a meaning
  `Enter` carries on some rows and not others. Its footer names what `Enter` will do to
  the row it is on, and names nothing on a leaf, where it does nothing.
- **`apply` and `discard` are on every level of the checklist, root and nested alike** —
  reachable only from the root is what the accept used to be, and on a tree whose paths
  all sit under folders that was a screen with no way to finish. `← Back` moves the cursor
  up a level and keeps every answer given; it is not a second `discard`.
- **What those two rows are called belongs to the caller, and their shape does not** —
  the close screen ends with `close` and `leave open`, because what it accepts is a close
  and `apply` would be one word doing two jobs. A caller supplies the labels and the
  panel line under each; it never supplies a key, a third row, or a level without them.
- **A checklist leaf has three answers, not two: in, out, and not yet answered** — and a
  leaf left unanswered has **no step written for it**, so it is offered again next time.
  Two states could not tell "kept out on purpose" from "nobody has asked", which meant
  accepting a screen filed a refusal for every row the user had not got to. `Space` never
  returns a row to unanswered: the first press answers it, and every press after it
  changes the answer.
- **Typing narrows a list on every list-shaped prompt, and by one implementation** —
  `ui/filtering.py`, called by `choose`, `browse` and `check`. A row is matched on the
  text it already draws; neither `Row` nor `Cell` grows a second "searchable text" field,
  because a field beside the cells is one more thing that can fall out of step with them.
  The cursor stays on the row it was on where that row still matches and lands on the
  first match otherwise, so narrowing never moves the answer out from under `Enter`. A
  screen's own action rows — the visible way back, `apply`, `discard` — are never filtered
  away, because an action row survives an empty list (docs/CONVENTIONS.md §12) and going
  back must not become a key you have to know.
- **Every screen's corner hint comes from one renderer** — `ui/footer.py`, given the keys
  that screen actually has. Four widgets each building their own footer string is how four
  answers to the same question came about, and a key added to a screen would then be a key
  its corner forgot to mention. A screen with no keys of its own (`text`, `confirm`) draws
  nothing, which is the same rule rather than an exception to it.
- **The listing never blocks on `gh`** — git status is collected before the first
  paint, pull request state fills in behind it. It is the difference between a
  screen that appears and one that appears two seconds later.
- **The listing's `pr` column distinguishes "asked and there is none" from "could
  not ask"** — `none` and `unknown` mean opposite things, and only one has a remedy.
- **The listing's row order never changes while it is on screen** — a cursor over
  rows that rearrange themselves is worse than no cursor.
- **Escape is not bound at all** — eagerly it swallows Option+Arrow; normally it
  takes over a second to register. Neither is acceptable and neither is needed.
- **Ctrl-C quits lane, wherever it lands, and never surfaces as a traceback** — a stack
  trace is the one outcome a user can do nothing with. At a prompt or a Zone 1 spinner it
  exits silently (`Quit`); anywhere else it exits after saying what may be half-done
  (`KeyboardInterrupt`); during a close's removal it is deferred, the phase finishes, and
  *then* it exits. Every one of those ends with the same farewell `quit` prints, and
  `cli.main` exits `130` for anything that escapes the session entirely.
- **Backing out is a visible row and never Ctrl-C** — `Abandoned` is what `← Back` and
  the checklist's `discard` raise, and it returns to the screen above. Folding it into
  the quit path would make `← Back` leave the application.
- **Every step slow enough to notice runs under `ui.progress`, including the ones
  after the last question** — the removal is the slowest thing a close does and the
  only one with no prompt on screen to explain the wait, so leaving it silent is
  what makes a working close look like a hung one.
- **A close's removal phase defers Ctrl-C; nothing else does** — half a removal is
  a state lane cannot describe or repair, and it is the only step with no question
  left to abandon. A second Ctrl-C is never deferred.
- **The terminal cursor is hidden in prompts** — otherwise it parks on the first
  character and reads as if that letter were selected.
- **"merged" is only said of a lane that has commits which reached the base** — a
  lane opened a minute ago is an ancestor of its base vacuously, and calling that
  merged tells the user their work landed when it never existed. A `MERGED` pull
  request counts as reaching the base, in the listing as well as in the close flow;
  `has_own_commits` still gates it, so this cannot resurrect the vacuous case.
- **The lane's starting commit is recorded in its metadata, and it is
  `merge-base(HEAD, origin/<base>)`** — it is the only thing that distinguishes "has
  done no work" from "work has landed"; both leave nothing ahead of `origin/<base>`.
  It is **not** "when did this lane begin": it is *the commit from which everything
  on HEAD is this branch's own work*. For a branch lane created at `origin/<base>`
  those are the same commit, so this is the value lane has always recorded — one
  rule, no branching on how the lane started. For a branch lane adopted, only the
  merge base is right: recording the tip would make the listing say `no commits yet`
  about a branch full of unmerged work, and make the close flow file "no commits of
  its own — nothing to merge" as a *clean note* directly above the confirmation that
  deletes them.
- **Path identity is asked of the filesystem, never compared as strings** —
  `samefile`, not `resolve() == resolve()`. macOS and Windows are case-insensitive,
  so `/users/me/projects` and `/Users/me/Projects` are one directory while their
  resolved strings differ; comparing strings once made every project vanish. It lives
  in **`lane/paths.py`**, once: the backend compares what git reports against what
  the user configured, and `open`'s branch list matches a worktree path to a lane, so
  a private copy each would be two places for one invariant to be got wrong.
- **`find_nested_repository` and `list_projects` use the same definition of
  "repository"** — when they disagreed, lane reported "no projects here" and then
  suggested a folder that had none either.
- **git's own refusals are never reimplemented or bypassed** — `worktree remove`
  without `--force` and `branch -d` are the safety net lane inherits by shelling
  out; `--force`/`-D` are used only where the user has just been asked.
- **Every question comes before the first irreversible step** — that is what makes
  abandoning a clean no-op and rollback logic unnecessary.
- **Branch deletion on close applies to the lane's own branches** — never the base
  branch, however often it was visited, and a detached lane has none of its own.
  **A lane that adopted an existing branch is not an exception**, and this was
  decided rather than inherited: closing deletes the *local* branch only, the remote
  one is never touched, and where nothing demonstrably landed git's own unmerged
  refusal still turns into the force-delete question. So a branch you merely
  borrowed is either safely reproducible from `origin` or is one you were asked
  about — which is the same protection every other branch gets, for the same reason.
- **Closing a lane deletes its local branch** — leaving it behind is how a
  repository fills with dead branches, one per lane ever closed. The summary states
  it before the user acts. Where the work demonstrably landed (git's ancestry
  check, or a `MERGED` pull request) it goes with **no row at all** — including
  the squash case, where `git branch -d` refuses and forcing is correct rather than
  dangerous. Where there is no such evidence the close screen carries a row for that
  branch, starting **out**; leaving it out keeps the branch and prints the command to
  remove it later.
- **All of them, not just the one the lane is standing on.** A lane is one task and a
  task can move through several branches; lane is absent while it does, so they are
  recorded nowhere but the worktree's own HEAD reflog — read from both sides of every
  `checkout: moving from A to B`, since the branch the lane was created on appears
  only as somewhere it moved *from*. Two consequences to keep: it must be read
  **before the worktree is removed**, because `git worktree remove` takes that reflog
  with it; and every name is filtered back through git, because reflog entries outlive
  the branches they name and a detached spell leaves a bare commit id behind. Those
  holding unique work are marked in the summary and get **a row each** on the close
  screen. One question covering all of them was the shape before, and it could only
  answer *all* or *none* — a lane that moved around twice usually wants one of them and
  not the other. A row costs no round trip, which is what a prompt per branch did.

## Behaviour to preserve

This is what lane does, not what you type.

**Names.** Task descriptions are typed in whatever language the user thinks in,
often with non-ASCII characters. Lane and branch names must always come out plain
ASCII: `Login sayfası hatası` → `login-sayfasi-hatasi`, using Unicode decomposition
for accented letters (Turkish dotless/dotted i and ligatures stay explicit because
decomposition gets those wrong), validated with `git check-ref-format`. Lane names
cap at 40 characters.

**Configuration** — `${XDG_CONFIG_HOME:-~/.config}/lane/`, directory mode 0700,
config file mode 0600, TOML (`tomllib` to read, `tomli-w` to write). Migrating a
config in the old shell-sourced format on first run is **required, not optional**.
Three settings — `projects_root`, `lanes_root`, `editor` — plus a version stamp.
`LANE_PROJECTS_ROOT`, `LANE_LANES_ROOT` and `LANE_EDITOR` override the file; when
one is active the settings action still edits the file but says plainly that the
environment is currently winning. A config written by a different version is
rewritten in place, carrying values over and keeping a backup, announcing itself
in one short line.

**The preparation answers** — `${XDG_CONFIG_HOME:-~/.config}/lane/prepare.toml`, mode
0600 in the same 0700 directory, a **flat array of `[[step]]` records** keyed by project
*name*. Deliberately **not** three more keys in `config.toml`: `ConfigStore.save()`
rebuilds the file from the three settings it knows about, so anything else in there is
dropped the first time a version bump rewrites it — and that migration code is the one
part of the config that must never be wrong. It is flat rather than nested because
nesting would put project names (which contain dots) and paths (which contain slashes) in
key position, where TOML wants them quoted, and the file would stop being readable. It
**never announces itself**: no rewrite, no `.bak`, no notice, because the upgrade notice
staying one short line is an invariant and a second file having something to say does not
serve it. An unreadable file means **nothing is remembered** — never a crash, never a
rewrite; the screen asking again is itself the signal, and doctor names the file.

**The branch prefixes** — `${XDG_CONFIG_HOME:-~/.config}/lane/branch_prefixes.toml`,
mode 0600 in the same 0700 directory, a flat `prefix = [...]` array of strings.
Deliberately **not** a fourth key in `config.toml`, for `prepare.toml`'s reason and one
more of its own: `ConfigStore.save()` rebuilds the file from the three settings it knows
about, so anything else is dropped by the first version bump — and `config.py` is explicit
that three settings is a closed list, which an unbounded, editable list of strings with no
per-value default, no environment override and no validation of its own does not join. It
is a flat array rather than records because a prefix is one string with no fields; a
`[[prefix]]` table per entry would be ceremony around a single value.

**A missing or empty file means the six lane ships with** (`prefixes.DEFAULT_PREFIXES`),
so nobody who never opens the screen sees anything change and there is no first-run write
to get wrong. Empty is the same answer as absent because a menu with nothing on it is not
something anybody chose, and forgetting the last prefix is how you would arrive at one —
so the screen **says** the six are back rather than letting them reappear unexplained.
Once anything is written, the file *is* the menu: the seed is never merged back in, or
forgetting one of the six could never stick. It **never announces itself**, and an
unreadable file means the seed rather than a crash or a rewrite — the six being on screen
again is itself the signal.

**Removing a prefix reaches nothing that already exists.** A branch is a ref that has
been pushed, reviewed and built on; a prefix leaving the menu says nothing about it. There
is deliberately no code connecting the two, and `test_forgetting_a_prefix_leaves_a_lane_
already_on_it_exactly_as_it_was` is what keeps it that way.

**Project identity is the project name** — the same identifier `Lane.project` uses and
that `<lanes_root>/<project>` is built from. A recorded path would be a string comparison
of paths, which is exactly what the `samefile` invariant exists to prevent, and it would
not survive moving `projects_root`; the name does. A *renamed* project is asked again,
consistent with lane already giving it a fresh lanes directory and a fresh listing. A
wrong key finds nothing — it never finds somebody else's answers.

**Convenience state** — anything lane remembers for convenience rather than
configuration (the last project used, for instance) lives in
`${XDG_STATE_HOME:-~/.local/state}/lane/state.toml`, mode 0600, **never** in the
config file. Adding to that file is not a new configuration key and does not need
asking; it is also disposable, so lane must behave correctly when it is missing or
corrupt. **Adding a new _configuration_ key does need asking.**

**Opening a lane** — pick a project from `<projects_root>/<project>/.git`, then
**one question with two answers**, and the flows diverge. Lane metadata —
description, base branch, created timestamp, repo path, starting commit — lives
**outside the worktree** so it cannot dirty it
(`<lanes_root>/<project>/.lane/<lane>`), and either path ends by entering the lane.

- **new work** — take a one-line task description, derive the lane name from it,
  fetch origin, resolve the default branch, then ask for the mode. Branch mode
  offers **each configured prefix** — `feature/`, `bugfix/`, `hotfix/`, `chore/`,
  `refactor/`, `docs/` until somebody changes them — plus the bare lane name and a
  free-text option. The bare name and `other…` are not prefixes and are always there;
  `other…` starts from the **first** configured prefix, because offering `feature/` to
  somebody who has just forgotten `feature` is the one wrong default. Detached mode sits
  at `origin/<default>` with no branch.
- **existing branch** — fetch with `--prune`, then pick from every local and
  `origin` branch, merged one row per name. **Detached is not offered here**: an
  existing branch is the opposite of detached.

*Not everything a lane is opened for is new.* Picking up a branch a colleague
pushed, coming back to something abandoned, reviewing a pull request locally — all
of them start from a branch that already exists, and doing it by hand left the
metadata describing something the lane is not. What the second path settles:

- **Unavailable branches are shown, and refused when chosen** — never hidden, per
  the rule that prerequisites are enforced where they are used. A row that is not
  there cannot explain why it is not there, and the default branch (always held by
  the main clone) plus every branch another lane has open is most of the interesting
  list. The `state` cell says which, in words. A branch held by a lane **offers to
  enter that lane instead**, because lane knows which one it is and that is a better
  answer than an error.
- **It is a `browse`, not a `choose`, and that was measured** — `picker.pick` draws
  every option into one window with no scrolling of its own, so 300 branches is
  **304 lines** with the cursor walking off the bottom of the terminal;
  `table.paint` windows the same list and footers `1–19 of 300`. Ordered
  most-recently-committed first, which is what puts the real answer in the first
  screenful. **No filtering and no cap**: typing-to-narrow changes what every
  printable key means inside a picker and is a decision for the maintainer, not a
  convenience to slip in; a silent cap would read as "this is all there is".
- **The lane name is `slugify(branch)`, shown for editing** — the branch was named
  by somebody else for another purpose, so the forty-character cap cuts it in a
  place nobody chose, and the name is a directory the user will live in. It is also
  the only place a collision can be resolved: unlike a description, a branch name
  cannot be reworded, so the prompt re-asks rather than refusing outright. **The
  prefix is not stripped** — it would buy about seven characters of the cap and cost
  a whole class of collision, since `feature/x` and `bugfix/x` both reduce to `x`
  and a lane name is a directory name.
- **The branch is the description.** The user typed nothing, and the branch is what
  they chose. The listing's panel drops a description line that repeats the *branch*
  line as well as one that repeats the name — the same rule, reaching a case it had
  never met.
- **Which worktree holds a branch is matched to a lane with `samefile`**, never as
  strings — `git worktree list` reports the case on disk while a lanes root keeps
  whichever case was typed. This is the invariant whose breach once made every
  project vanish. The three ways a branch can be taken — a lane, the main clone, some
  other worktree — are told apart by **asking, not by elimination**: not every
  worktree is one of lane's, so "it is not a lane" does not mean "it is the main
  clone", and naming the wrong place sends the user to look in it.

**Preparing a lane** — a lane is a fresh checkout, so **everything `.gitignore` covers
is missing from it**: dependency trees have to be rebuilt, and an ignored `.env` cannot
be rebuilt at all. Preparation is the repair, and it belongs to **`enter`**, which
therefore no longer means "launch the editor" but **"make the lane ready, then launch the
editor"**. `open` ends by entering the lane it created, so there is one code path rather
than two.

- **Two verbs, and lane learns no package manager.** `clone` (a copy-on-write copy from
  the main clone) and `run` (a configured command, with a directory). Go keeps its caches
  globally and needs almost none of this; Node keeps them per project and needs all of it —
  an asymmetry lane cannot learn its way out of, since there is always one more ecosystem.
  The mechanism is generic; the project-specific knowledge is configuration.
- **`link` was a third verb and is gone, on purpose.** It made a symlink into the main
  clone: always current, one copy rather than one per lane, which suited a large read-only
  asset and suited secrets. It was removed because **a row asks one question with two
  answers** — does this come into the lane — and one keystroke cannot carry a third thing
  to *do*; a screen that had to be entered to change an answer is what the whole rebuild
  was for. Not to be confused with the row's three **states**: *not yet answered* is the
  absence of a decision, not a third thing lane can do to a path. Consequences to keep rather than rediscover:
  a `verb = "link"` in an older `prepare.toml` is dropped on read like any unknown verb, so
  that path is asked about again and the symlink already in the lane reads as *already
  there*; and the trailing-slash `linkable` question went with it, while the **`writable`
  half of the same bulk `check-ignore` stayed**, because that is what stops a tracked path
  ever being offered. Do not reintroduce `link` as a hidden setting: it would be a third
  third verb wearing a different hat.
- **`refresh` went with it.** A `clone` step could be marked "reapply on every enter",
  settable only in settings — and settings' per-step editor is exactly what the checklist
  replaced, so it had nowhere left to be set. Removing it also made the overwrite rule
  unconditional, which is worth more than the feature was: see the invariant below.
- **Discovery is git's own answer**, not a guess:
  `git ls-files -o -i --exclude-standard --directory -z` against the **main clone**,
  where the files are. `--directory` is what makes it usable — one row for
  `node_modules/`, not two hundred thousand. Rows nested inside another row are collapsed
  to the shallowest, because git reports both when an intermediate directory holds
  nothing tracked, and applying both would write the same bytes twice.
- **Only paths the lane's own git ignores are ever written**, asked in one bulk
  `check-ignore --stdin -z`, in **both spellings**. The trailing slash is the whole
  question: `node_modules/` matches directories only. A path ignored in neither spelling is
  one the lane's branch tracks or simply does not ignore, so writing there would dirty the
  worktree — and it is not offered at all. A tracked path never comes back, which is what
  stops lane writing over one.
- **One screen, one component, two callers.** Entering a lane opens it when some path has
  no answer yet, and not at all otherwise; settings · preparation opens it to review or
  change anything. **Not two screens that resemble each other** — one `Ui.check`, one
  `prepare.Sheet` building the rows, opened from both places, because resemblance drifts
  and sameness cannot. It had already drifted: entering cycled a row in place while
  settings made you press `Enter`, choose *change*, and pick a verb — three screens to move
  one path, a dozen times over for a dozen paths.
- **A path is in, out, or not yet answered — and only the first two are ever stored.**
  `✓` means the path comes into the lane and `✗` means it stays out; both are written down.
  `○` means nobody has said, which is where every row starts, and it writes **nothing** —
  so `prepare.unanswered` offers that path again next time, exactly as it would one nobody
  has ever seen. That is what makes `apply` safe on a screen with unanswered rows still on
  it: it commits what was decided and leaves the rest, rather than filing a refusal on the
  user's behalf. `Space` never returns a row to unanswered.
  **`◐` and `?` are not answers for a path**: they are folder rows saying that the paths
  under them disagree, or that one of them is still unanswered.
- **Two states could not say this, and the cost was real in both directions.** Accepting a
  screen recorded `skip` for every row the user had not got to, so a path skipped past once
  was never offered again; and in settings a stored `skip` and a path never asked about
  drew the same blank gutter, which is the same ambiguity seen from the other end.
- **`Space` on a folder sets every leaf under it to one answer, and anything short of
  *all in* goes *in*.** All in becomes all out; everything else — all out, a mix, or
  untouched — becomes all in, because *in* is what somebody reaching for a directory row is
  after, and because the alternative collapses a mix to *out*, which is the answer that
  quietly leaves work undone. **Unanswered counts towards "not all in"**, so one press on a
  folder nobody has touched brings the whole subtree in. The mix it
  replaces is not recoverable, which is why the row's panel says how many it is about to
  move before the key is pressed.
- **A path answered *in* that is already in the lane is left alone rather than
  overwritten.** The mark cannot carry this, so it is stated once and holds always — and
  because it holds always, one function (`prepare.needed`) decides what every step does,
  where there used to be two that disagreed on exactly this point. The row says
  **`already there`** in its own column, and the cursor panel repeats it, because an answer
  that is a no-op and one that copies a gigabyte have to look different. This is a
  different axis from the answer itself and both stay visible: *is it already on disk* and
  *have you decided to bring it in* are separate questions.
- **The screen carries a running count of what is in**, and beside it how much is about to
  be copied (`4 of 6 in · 1.2 GB coming in`). Forty rows do not fit on a terminal, so
  without it the only way to know what you have just decided is to scroll back through it.
  The count is the widget's, because it owns the answers; the size is the action's, because
  it owns the sizes. Paths already in the lane are left out of the total — an answer on one
  of those does nothing, and counting it would describe work lane is not going to do.
- **The rows are a tree, one level of it per screen**, because `--directory` only
  collapses a directory git ignores *entirely*: one tracked file in it and every ignored
  file inside is listed separately. Measured on a four-pattern repository: **55 rows, 40 of
  them from one `logs/`** — and a real monorepo reaches around two hundred, scattered
  `node_modules`, `dist` and `.env` under package after package. `prepare.tree` groups
  discovery's own answer on its separators; **no second git call and no walk of its own**.
  A folder row is entered with `Enter` and answered whole with `Space`.
- **A level of fewer than three rows is drawn in its parent.** A folder row costs one press
  to reach the rows inside it, so it has to save more than one row to be worth having: two
  folded into one is a wash, three saves two (`prepare.GROUP_FROM`). A directory with a
  single child is the extreme of the same rule — no choice is being offered, so a chain
  like `apps/web/frontend/node_modules` stays the one row it always was.
- **The repository root is the one level that folds its own loose files**, into `./`. Every
  other directory already has a row on the screen above it to be answered from; the root
  has none, so `./` is the only place its loose files can be answered in one keystroke.
- **A folder is folded whatever its paths were answered.** A directory holding two `.env`
  files that are in and thirty logs that are out draws `◐`, which is exactly what it is;
  one where half of them are still unanswered draws `?`, which is a different fact and gets
  a different mark. This is the one thing the flat screen could not do: a checkbox has two
  states, so such a folder had to be opened out into its own rows instead — truthful, and
  the flat run of rows this shape exists to replace. Entering a lane now reaches `?` on its
  first screen, where every leaf starts unanswered; `◐` still arrives only from answers
  already on disk, which is why settings is where it turns up.
- **A folder is presentation, never a step for its directory.** The directory is only
  partly ignored — that is why its files were listed one by one — so it holds tracked work
  too, and cloning it would overwrite that. Answering a folder stores one step per path.
  A file that appears there later is therefore a path nobody has answered, and is asked
  about rather than silently swept in.
- **Nothing is recorded per lane.** The only state is the filesystem — is the path there —
  which is what makes a failed or interrupted preparation repair itself.
- **The answers live in `prepare.toml`, beside the config and never inside it.** See
  *Configuration* below.
- **Settings holds the commands separately, and that is not drift.** `preparation` is the
  shared checklist over paths; `commands` is a fifth settings row holding the `run` steps,
  with `change`/`forget` and `add a command`. A command is typed rather than discovered and
  carries a directory and a guard to edit, none of which is a checkbox — folding it into a
  screen of discovered paths would be the resemblance this change exists to remove.
  **`branch prefixes` is a sixth row of exactly that shape** — its own list, `change`/
  `forget` on the row under the cursor, `add a prefix` appended the way `← Back` is — and
  it is a destination rather than a setting, so a noun (`docs/CONVENTIONS.md` §4). It
  belongs to neither of the other two: it is about naming a branch rather than about what
  comes into a lane, and it lives in its own file, not in `prepare.toml`.
- **Copy-on-write is `clonefile(2)` via `ctypes`, not a subprocess to `cp -c`.** Measured:
  a 64 MB tree in 0.3 ms, and across volumes it fails with `EXDEV` having done nothing.
  `cp -Rc` takes 9 ms and, across volumes, **silently** falls back to a real copy —
  documented in `cp(1)`, and observed filling a small volume, exiting 1 and leaving a
  partial file behind. The user configured this expecting it to be free; the least lane
  owes them is to know when it was not. The fallback is `shutil`, so nothing is spawned to
  copy anything, and doctor reports whether the two roots can share blocks at all.

**Listing lanes** — for each lane: uncommitted count, unpushed count, merged flag,
detachment, pull request state and age, on a row you can put a cursor on. The
branch is shown too, but in the panel for the row under the cursor rather than in a
column: it is the lane name with a prefix in front of it, and spending forty
columns on it was what left `state` and `pr` — the two that answer *can I close
this* — as the narrowest things on the line. See *The lanes screen* above.

**Closing a lane** — fetch, then three checks: uncommitted or untracked files,
unpushed commits, and whether the work reached `origin/<default>` (including the
pull request check). Everything the close needs to know is decided **before anything
is removed, on one screen**: the findings and the "About to remove" block are printed
as facts, and then a `check` whose rows are exactly the decisions that apply — a
`wip/<lane>` rescue when a detached lane has commits that would be stranded (starting
**in**), one row per branch git would refuse to delete (each starting **out**), and
`close` / `leave open` always. Only then does it execute: park the rescue branch if
asked, remove the worktree, prune, delete the branches.

**It is a screen rather than a chain of confirmations, and that was the last holdout.**
Closing used to ask up to four yes/no questions in a row whose defaults disagreed with
one another — three declining and one accepting — inside what reads as one flow. A lane
with nothing optional to decide gets the **same** screen with only its two last rows: one
shape everywhere beats a shortcut for the easy lane. `leave open` says so in a line and
touches nothing, which is what declining always did. **Every one of
those steps shows a spinner** — they run after the last question, with nothing on
screen to explain the wait, and removing a worktree of a few thousand files is the
longest thing a close does. **The whole phase defers Ctrl-C**, which is Zone 2 of
*Ctrl-C quits lane* above.

**Diagnostics** — when no projects are found, say how many subfolders were looked
at, and if the repositories turn out to be nested (`<root>/<org>/<repo>`), point at
the folder that should be used instead. Doctor reports the state of every
prerequisite and **must render that report on a machine where none of them is
present**. Doctor also answers "am I running the copy I just installed": under
PyInstaller one-file `__file__` points into a temporary extraction directory, so
report and fingerprint `sys.executable` — the installed binary — not the extracted
sources.

## How to work on it

Test-driven, genuinely. For every behaviour: write the failing test first, make it
pass, then tidy up. **No production code without a test that demanded it.** If you
notice you have written untested code, delete it and do that piece again.

Tests run against **real temporary git repositories** (a bare "remote" plus a
clone), so worktree creation, fetching and merge detection are exercised for real.
The fakes are exactly the three named above. The suite must never authenticate to
GitHub, reach the network, or open an editor.

```
make test     # pytest
make lint     # ruff check + ruff format --check
make types    # mypy --strict
make build    # PyInstaller one-file -> dist/lane
```

### Landing a change — main is protected

**Nothing is pushed to main.** A branch ruleset on the default branch requires a
pull request and refuses direct pushes, force-pushes and deletion, with **no bypass
actors** — the maintainer included. There is one contributor, so the rule has to
hold without anybody to enforce it, and an owner who can push directly is a
protection that is only ever advisory.

**The pull request requires no approving review.** GitHub counts "a pull request is
required" and "an approval is required" separately, and this repository asks for the
first and not the second: the sole contributor cannot approve their own work, so any
non-zero count would mean the branch could never be merged into. The gate is
therefore not a human — it is `CI / check`, which must be green before the merge
button unlocks. Two settings hold that open and are easy to break by accident:
`require_last_push_approval` must stay false, or your own final commit needs
somebody else's approval, and the bypass list must stay empty.

**Strictness is deliberately off** (`strict_required_status_checks_policy: false`),
so a pull request need not be rebased onto main before merging. lane exists to run
several branches side by side; requiring each to be brought up to date would mean
re-running CI over the whole stack after every merge. The cost is real and worth
naming: two changes that pass separately can break together, and nothing on main
will notice until the next pull request runs. If that ever actually bites, turning
strictness on is the fix.

**Three workflows, each doing one thing once:**

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | pull request | lint, types, tests, build, smoke — the required check |
| `build.yml` | push to main | builds and uploads `lane-macos-arm64`. **No tests** |
| `cd.yml` | `v*` tag | rebuilds, verifies the tag, publishes the release |

`build.yml` runs no tests because the pull request that produced the commit already
ran them. It still builds and smoke-tests, because the thing it is building is the
merge commit and no pull request ever built that. Its artifact is an unreleased
build of main for trying something that has landed but not shipped — GitHub serves
it as a zip, so a download needs `chmod +x`.

**The required check is named `check`.** That is the job id in `ci.yml`, and the
ruleset names it as a string. Renaming the job, or splitting it into several, leaves
the required check waiting as *expected* forever with nothing anywhere saying why.
Change both or neither.

### The two structural rules that erode first

1. **Actions ask through the prompt interface; they never import a prompt
   library.** The moment an action imports `prompt_toolkit`, it stops being
   testable without a terminal.
2. **Everything touching git or GitHub sits behind its interface.** No `subprocess`
   call to `git` or `gh` outside the backend/client implementations. Preparation's
   discovery is a git call and lives in the backend for that reason; copying is not git,
   and lives in `prepare/apply.py` — the only module that clones, links, runs a configured
   command or measures a path.

### Standards

**Python 3.14** (`requires-python = ">=3.14"`, ruff `target-version = "py314"`,
mypy `python_version = "3.14"`), `uv` for dependencies and the virtualenv,
`pyproject.toml`, `src/lane/` layout. stdlib `argparse` for the command line,
subparsers included — **do not** pull in Typer or Click. That rule was written when
there were two flags to parse and is unaffected by there now being five subcommands:
`argparse` also generates `--help` from the same definition, which is the whole reason
the help text is no longer written by hand. Prompt and
rendering libraries are confined to the presentation layer. Full type hints,
`mypy --strict` clean, `ruff` for lint and format. `pytest`, `pre-commit`, and CI
running lint, types and tests.

3.14 is the floor because lane is distributed as a self-contained binary — the
runtime is whatever the build used, and there is no user-installed interpreter to
stay compatible with. Do not raise the floor to a pre-release Python version.

### Packaging

PyInstaller, one-file, macOS arm64 first. `make build` produces `dist/lane`. CI
runs the built binary's `--version` as a smoke test: it is the one path guaranteed
to work without a TTY, and it catches missing hidden imports at build time rather
than later. The build fingerprint is a **hash of the running executable** — that is
what answers "did this file change", the question doctor exists to settle.
Stamping the git commit as well is fine, but the hash is the part that must work.
Room is left for macOS x86_64 and Linux later; that matrix is not built yet.

### Releasing

**The tag is the version.** `hatch-vcs` derives it from `git describe` and writes
`src/lane/_version.py` at install and at build time; that file is gitignored, and
**no file in the tree carries the number**, so no file in the tree can disagree
with the tag. Do not reintroduce a hard-coded `__version__` — the reason this is
worth a rule is that a second copy of a version number is only ever wrong later,
and silently.

Releasing is one step:

```
git tag -a vX.Y.Z -m "..." && git push --tags
```

`.github/workflows/cd.yml` does the rest: it builds the binary, **refuses the
release if the binary's `--version` does not match the tag**, and publishes a
GitHub release with the binary attached. The refusal exists because a wrong
version number is invisible until someone reports a bug against it.

**There is a second door, and it is GitHub's rather than ours: publishing a release
from the web UI creates the tag as a side effect**, which triggers this workflow. So
the release can already exist by the time CD runs, and CD **adopts it** — uploading
the binary with `--clobber` and leaving its title and notes alone — rather than trying
to create one and failing. That is not a workaround for a mistake; it is what makes the
step idempotent, which also means a run that failed *after* creating the release can be
retried. v0.0.5 is why this is written down: it was published from the UI, `gh release
create` refused, and the result was a published release with **no binary on it** while
the README's `releases/latest/download/lane-macos-arm64` install pointed at nothing.
**The binary being attached is the invariant; being the thing that created the release
is not.**

The tag command above is still the route to prefer, for one concrete reason beyond
habit: it makes an **annotated** tag, and the UI makes a lightweight one.

**It rebuilds, and must keep rebuilding.** `build.yml` has already produced a binary
for that exact commit, and publishing it instead looks like free speed — but the
version comes from `git describe`, so a binary built on main before the tag existed
reports `0.0.2.post1.dev0+g1a2b3c4`. Reusing it would ship every release labelled as
an unreleased development build, and the tag check above would have to be deleted to
allow it. Two minutes of rebuild is what makes that check mean something.

**The notes are generated from the pull requests** merged since the previous tag,
grouped by the labels in `.github/release.yml`. Nothing is written by hand and
nothing is committed for a release, which is the point: a changelog that has to be
edited before a tag is a second copy of the release's identity, and a second copy
is only ever wrong later. Labelling a pull request `enhancement` or `bug` is what
shapes the notes; an unlabelled one still appears, under *Other changes*. **Every
label that file names must exist on the repository** — a category matching a label
nobody can apply never fires, and nothing reports that it didn't.

Between tags the version reads `0.0.2.post1.dev4+g1a2b3c4` — "after 0.0.2,
unreleased", deliberately not a version that does not exist yet. The config stamp
asks for the **release** rather than the build, via `buildinfo.release()`: it is
compared on every load, so stamping the full version would rewrite the file, and
leave a `.bak` beside it, on every run of a development checkout.

### Coverage floor

All of it arrived at test-first:

- transliteration of lane and branch names
- default-branch detection, including a `master` repository
- all three close checks
- the squash-merge false negative resolved by a stubbed `MERGED` pull request
- the detached-HEAD rescue, asserting the `wip/` branch survives
- config migration from the shell format to TOML
- the picker auto-selecting a lone candidate and re-prompting on bad input
- the lanes table's cursor, its visible back row, its narrow-terminal degradation
  and its scrolling — all through pipe input and a stated terminal size
- the listing's rows being complete, with `pr` still a placeholder, **before** any
  `gh` call is made
- closing a GitHub-backed lane refused with a usable message when `gh` is missing
  or logged out, while closing a lane with a non-GitHub remote still succeeds
- the close screen carrying exactly the rows that apply — the rescue only where commits
  would be stranded and starting *in*, a branch row only where `-d` could lose something
  and starting *out*, none at all for a lane with nothing left to decide — and two
  unmerged branches a lane used being answered one way each
- `leave open` leaving the worktree, every branch and the metadata exactly as they were
- every step of a close's removal phase announcing itself, in order, after the last
  decision
- Ctrl-C during that phase finishing it rather than stopping half-way — a real
  `SIGINT` to the test process, because that is what a terminal sends — being raised
  afterwards rather than discarded, and the session then **exiting** rather than
  reporting it and showing the menu again, with the ordering asserted so the removal can
  never interleave with the exit
- Ctrl-C during a spinner quitting lane, Ctrl-C inside an action being reported with
  what might be half-done and *then* quitting, Ctrl-C at a bare menu prompt still
  quitting, and the boundary exiting `130` rather than tracing back
- git running outside lane's process group, so the terminal's Ctrl-C cannot reach it
- a non-TTY invocation refusing cleanly while `--version` still works
- the version reaching the build from the tag, and the config stamp being the
  release rather than the moving version of a development checkout
- at least one test driving the session end to end: menu → open a lane → menu →
  lanes → close it → menu → quit, asserting the resulting git state
- discovery listing one row per ignored directory, and collapsing a row nested inside
  another; the ignore question distinguishing `x/` from `x` and never returning a tracked
  path
- `Space` answering the row under the cursor without moving it, several rows all landing,
  `apply` accepting the whole screen, and the widget binding the picker's keys plus `Space`
  and nothing else — all through pipe input
- a leaf cycling unanswered → in → out → in and never back to unanswered, and all five
  folder states over the **whole** partition of in/out/unanswered rather than a sample
- `Enter` doing nothing on a leaf at the root and two levels down, opening a folder at
  both, leaving a level from `← Back` without discarding what was answered inside it, and
  `apply`/`discard` being reachable at every depth
- applying with rows still unanswered writing steps only for the answered ones, and the
  untouched paths being offered again on the next visit
- the screen not appearing at all when no path is unanswered, and the same component being
  the one settings opens — counted, not eyeballed
- a path answered *in* that is already in the lane keeping the lane's own copy, with the row saying
  `already there` and nothing being applied
- a clone reproducing a tree, the copy being independent of it, and a failed swap leaving
  the original whole with nothing staged behind
- a clone that fell back to a real copy **saying so**, since that is the entire reason
  `clonefile` is called instead of `cp -c`
- entering an already-prepared lane making **exactly one** git call, asking nothing and
  drawing nothing — counted through the real backend
- the table binding no key beyond the picker's set, and the checklist binding exactly
  that set plus `Space` — asserted on both binding tables, not by driving keys
- the mark surviving a 40-column terminal while the other columns are dropped and the
  path truncates, and the footer giving up the arrows before it gives up naming the keys
- a failed step reporting its fix while the remaining steps still run and the editor still
  opens; entering again finishing what it left
- Ctrl-C during a step naming the step, saying entering again finishes the job, and not
  launching the editor
- a prepared lane still reading `✓ clean` to git, so preparation cannot leak into the
  listing's `state` cell or the close flow's checks
- forty loose ignored files in one directory drawing **one** row, answered by one
  keystroke — writing one step per path and never touching the directory, which a tracked
  file in it proves — and a folder whose remembered answers disagree keeping that one row
  and drawing `◐` on it
- settings, over a project with a stored `clone`, a stored `skip` and a path with no
  stored answer at all, drawing three visibly different marks — which two states could not
- nine ignored paths scattered under three packages opening on **one** row rather than
  nine, the level below it being the packages rather than their files, and one keystroke
  at the top of that tree writing nine steps and no step for a directory
- a chain of directories with a single child collapsing to the one row it was always
  about, and a level of two rows being drawn in its parent rather than behind a keystroke
- `Enter` opening the folder under the cursor, a level returned to having its rows and
  its cursor exactly as they were left, and an answer given two levels down surviving a
  walk back out and into a different folder
- the branch list merging a branch that is both local and remote into **one** row,
  excluding `origin/HEAD` (which `refname:short` renders as a bare `origin`), and
  putting the most recently committed first
- a branch that exists only on the remote adopted into a lane whose branch then
  tracks `origin/<it>`, while an adopted **local** branch keeps whatever upstream it
  already had and is never given one it did not
- a branch checked out in the main clone **shown** and refused with the reason and
  the path; one held by another lane naming that lane and offering to enter it, with
  declining returning to the list rather than leaving the screen
- the derived lane name offered with the branch's slug as its default, and a branch
  slugging to an open lane's name re-asking rather than aborting
- the starting commit of an adopted branch being the merge base, so a branch
  carrying somebody else's unmerged commits reads `not merged yet` and never
  `no commits yet` — and the starting commit of a new branch being unchanged, which
  is what makes it one rule
- the branch table surviving 40 columns with `state` intact, and an adopted lane's
  panel drawing its branch once rather than twice
- a subcommand given every flag producing the **same lane** as the menu given the same
  answers — same worktree, same branch, same metadata — which is the test that would
  notice a second implementation appearing
- every subcommand running the very action the session runs, asserted by replacing
  those functions and watching each one be called
- a missing flag with no terminal refusing by name, with its flag, and **not hanging**;
  the same missing flag with a terminal falling through to the real prompt, driven
  through the existing `FakeUi`
- a flag value that names nothing on the screen refused rather than re-asked, and
  refused with a terminal present too
- `--json` parsing on every subcommand, with **stdout carrying nothing else** — and a
  refusal in `--json` mode leaving stdout empty rather than half a document
- `close --delete-others` keeping one abandoned branch and dropping another, which is
  the one thing the command line can do that a single question never could
- a close flag naming a branch this close never offered refused **before** anything is
  removed, and a row flag without `--yes` refused rather than half-applied
- entering a lane with an unanswered ignored path and no terminal refusing without
  applying anything
- `lane --help` and `lane <command> --help` asserted against `argparse`'s own
  rendering of the parser, never against a second string
- the documented exit codes, pinned as a table
- the branch prompt offering the **configured** prefixes and not the ones that were
  forgotten, with the bare name and `other…` surviving either way, and `other…`'s default
  following the first configured prefix rather than a hard-coded `feature/`
- an absent and an empty `branch_prefixes.toml` both meaning the six, and an unreadable
  one meaning them too rather than raising
- adding, changing and forgetting a prefix each round-tripping through the file — the add
  writing the seed *plus* the new one, the change keeping its place in the order, and the
  forget of the last one saying the six are back
- a prefix validated the way a whole branch name is, so `  şube fix!!  ` stores as
  `sube-fix` and one git will not take is refused rather than left on the menu
- forgetting a prefix leaving a lane already on it exactly as it was — its branch, its
  metadata and its row in the listing untouched

## Where things stand

`docs/adr/` holds decisions that needed evidence: `0001-git-backend.md` and
`0002-lane-listing.md`. `docs/CONVENTIONS.md` is the presentation rulebook every
screen is held to — read it before laying out a new one.

**Precedence when sources disagree**: this file wins over your own judgement.
Where it is silent, decide for yourself and say so, and update this file in the
same change if the decision should bind future work too.
