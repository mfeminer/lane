# Presentation conventions

Rules a new screen must follow, each with the one-line reason. **Where AGENTS.md or
an ADR already decided something, this file cites it instead of restating it in
different words** — a second description of the same behaviour is the fault this
file exists to stop, not a service.

If you are building a new screen and this file doesn't answer your question, that's
a gap: raise it rather than guessing, and add the answer here once it's settled.

## 1. Screen anatomy

- **Every action-level screen opens with `ui.heading`, once, naming the screen**:
  `"lane doctor"`, `"lane settings"`, `"Closing <lane>"`. The
  lanes table is the original exception, and it's deliberate: its title *answers* "what
  am I looking at" (`"3 open lanes in demo"`) rather than repeating the word "lanes"
  — see ADR 0002. A new screen gets a heading unless it is, like the table, a screen
  whose title can say something more useful than its own name. **The branch list —
  `open`'s second path — is the second such screen**, and it takes the exception on
  exactly those terms: `"312 branches in Acme.Widgets"` answers what you are looking
  at, and a `lane branches` heading above it would be the repetition this rule
  exists to stop. Two screens is not a pattern to spread; a third needs the same
  argument made again.
- **One blank line between logical groups of output, none within a group.** A
  "group" is: the heading and its immediate context; each self-contained check or
  question; the final outcome. Doctor's tool checks, settings' three questions (no
  blank line *between* them — they are one flow), and the close summary's findings
  vs. its "About to remove" block are the reference shape. *Why: the three report
  screens were close to this but not identical, with no written rule to check a
  fourth screen against — this is that rule.*
- **The session — not an action — opens with the splash and closes with the
  farewell.** `session.run()` lays the road once at the top (`Ui.splash`, drawn by
  `ui/splash.py`) and closes it on the way out (`Ui.farewell`), by both doors: `quit`
  and Ctrl-C at the menu. This is the one screen that is drawing rather than
  reporting, so it is pinned whole in `tests/test_screen_snapshots.py` — nothing else
  in the app would notice a wheel moving or the wordmark drifting off centre. It
  changes nothing above: an action screen still names itself with `ui.heading`.
- **The subject of an action (which lane, which project) is named once, in the
  heading or the first line, never repeated as a running header.** `"Closing
  demo/broken-pagination"` names it once; nothing after that re-states the lane
  name unless a fresh fact needs it attached (the branch line, the pull request
  line).

## 2. Navigation and exits — going back

**Decided in AGENTS.md, cited not restated**: going back is a visible entry, never
only a key; every `choose` prompt ends with `← Back`, the lanes
table ends with `← Back to the menu`, the main menu ends with `quit`. These are
deliberately different labels for deliberately different scopes (one step back vs.
leaving the table entirely) — ADR 0002, "The screen" — do not unify them.

**`text` and `confirm` are the two prompts this rule cannot reach**, and that is now
stated rather than papered over. There is nothing to choose between in either, so there
is no row to add — and they used to render a dim `ctrl-c back out` footer instead,
because Ctrl-C meant something lane-specific there and relying on that being universally
known was judged insufficient.

- **That hint is gone.** Ctrl-C is not lane-specific any more: it quits lane, which is
  what every terminal user already assumes, and a footer teaching that teaches nothing.
  See *Ctrl-C quits lane* in AGENTS.md.
- The consequence is named there too: these two prompts have **no way back at all**, only
  a way out of lane. A mistyped answer is corrected from the screen that follows, not by
  backing out of the prompt. If that turns out to bite, the fix is to give them a visible
  way back — not to give Ctrl-C a second meaning.
- Do not add a rendered `← Back` *entry* to `text`/`confirm` on that account without
  deciding it deliberately: a picker with an extra row is a different widget from a
  question with one answer.

**The checklist has both kinds of row**, and it is the reference for a screen that needs
a way forward as well as a way back: `← Back` where there is a level above, then the two
that end every level, on every level. Accepting and abandoning are rows there for exactly
the reason going back always has been — a screen whose way forward is a keystroke you have
to know is the same fault as one whose way back is.

**The words on those two rows belong to the screen, and the shape does not.** `apply` and
`discard` are what a screen of ignored paths does; the close screen ends with `close` and
`leave open`, because what it accepts is a close and one word doing both jobs is how a
word stops meaning either (§14). A caller supplies the two labels and the panel line under
each (`seam.Finish`) — never a key, never a third row, never a level without them.

**The close screen is the second screen to take this shape, and it replaced a chain of
confirmations.** Up to four `y`/`n` questions in a row, whose defaults disagreed with one
another — three declining and one accepting — inside what read as a single flow. Its rows
are now exactly the decisions that apply, with no fixed count, and a lane with none of
them still gets the same screen with only `close` and `leave open` on it. **One shape,
always**: a bare confirmation for the easy lane and a screen for the awkward one would be
two ways of saying the same thing, which is the fault §14 exists to stop, one layer up.

## 3. Key bindings

**Fully decided in AGENTS.md and `picker.py`; cited, not restated.** The whole
vocabulary: `↑` `↓` `Home` `End` move, `Enter` chooses or acts on the row, `y`/`n` answer
a yes/no question, `Ctrl-C` **quits lane**, everywhere. No `q`, no vim keys, no digit
shortcuts, no Esc — each removed on purpose, with the reasoning kept in
AGENTS.md's "Going back is visible" section. **A new screen introduces no key this table doesn't already
have.** If a screen seems to need one, that is a decision for the maintainer
(AGENTS.md says so explicitly), not a convenience to slip in.

**Typing filters, on all three list-shaped prompts, and it is a deliberate addition
rather than a thing that showed up** (`ui/filtering.py`, reached through `Ui.choose`,
`Ui.browse` and `Ui.check`). It passes exactly the test `Space` had to pass: nothing
printable was bound in any of the three, `y`/`n` living only in `confirm` and `Space`
only in `check`, so a letter cannot collide with anything already there. One
implementation for all three, for the same reason those three widgets already share
their layout.

- **`Space` is not a filter character anywhere**, including the two screens where it is
  unbound. It already answers a row on one of the three, and a key that means one thing
  on one list screen and another on the next is what the closed vocabulary exists to
  prevent. A filter is one word — which is what a filter over paths, lane names and
  branch names is anyway.
- **`Backspace` takes the last character back, and no key clears the filter.**
  Backspacing to empty is the text editing `Ui.text` already relies on, reused rather
  than invented.
- **It is never a hidden mode.** What was typed is on screen, immediately under the
  title: `<n> of <total> · filter: <text>`. Where it matches nothing, that line is the
  empty state instead (§12), and the corner says `type to filter` (§3a).
- **A screen's own action rows are never filtered away** — the visible way back, and the
  checklist's `apply`/`discard`. §12 already says an action row survives an empty list,
  and a filter that could hide the way back would make going back a key you have to know.
  In `choose` the way back is the row `ConsoleUi.choose` appends, so the picker is told
  how many trailing entries are the screen's own (`pick`'s `tail`). Where a caller passes
  `back=None` its own list holds its exit — the menu's `quit`, the listing's `← Back to
  the menu` — and those filter like any other entry; `Backspace` and `Ctrl-C` are both
  still there, and this was judged the smaller inconsistency of the two available.

**One widget adds one key, and it is `Space` on the checklist** (`ui/checklist.py`,
reached through `Ui.check`). It is the widget where every row carries its own answer —
which ignored paths come into a lane, and what closing a lane does — and it spends the
vocabulary budget deliberately rather than by accident. **The second screen to use it
added no key of its own**, which is the test the budget was being spent against:

- `Space` answers the row under the cursor. It is the universal multi-select convention,
  it is what makes a dozen answers a dozen keystrokes, and the alternative — `Enter`
  cycling the row in place — is what this screen replaced, because it left the screen with
  no key to *accept* with and forced a `continue` row to stand in for one. On a **folder**
  row it answers every path beneath it at once, which is the whole point of the folder.
- **`Enter` does to a row exactly what that row *is*.** It opens a folder, leaves the
  level from `← Back`, accepts from `apply`, abandons from `discard`, and on a **leaf**
  does nothing at all — a leaf's answer is `Space`'s job and there is nothing to open. So
  `Enter` here means what it means everywhere else in lane: act on the row under the
  cursor. **There is no longer an exception**, and the one there used to be is worth
  keeping written down: `Enter` opened the row if it opened and *otherwise accepted the
  level you were standing in*, which sent a press on a **file** up out of the folder it
  was pressed in, and left the accept reachable only from a root-level leaf — a screen
  with no way to finish at all when every path sits under a folder.
- Accepting and abandoning are **rows**, on every level (§2). That is what removed the
  exception rather than moving it: a screen where `Enter` both answered the row and
  accepted would need a third key, and one where accepting is a row needs none.
- The footer names whichever of `open` / `go up` / `apply` / `discard` `Enter` will
  actually do to the row under the cursor, and names **none** on a leaf, because naming a
  key that does nothing teaches a lie (`checklist.keys_for()`, drawn by `ui/footer.py`
  like every other screen's — §3a). It does not
  name `ctrl-c`: that is no longer this screen's way out, and what it does now is the one
  thing about a terminal program nobody has to be taught. The lanes table's footer names
  nothing, because the table adds no key.

That is the whole exception, and it is one widget wide. **A new screen still introduces no
key**; if it seems to need one, that is a decision for the maintainer, made in the open
like this one, not a convenience to slip in.

## 3a. The corner hint

**One renderer draws every screen's footer** — `ui/footer.py`, called by `picker.py`
(`choose`, and `confirm`'s frame), `table.py` and `checklist.py`. Each screen says
which keys it has (`picker.KEYS`, `checklist.keys_for()`) and the renderer decides
what the corner says about them. *Why: the mechanism was the checklist's alone —
three tiers, shrinking as the terminal narrows — and every other widget carried a
constant of its own, which is how four screens came to hold four answers to the same
question. A key added to one screen now shows up in its corner without a widget being
touched.*

- **Bottom-right, dim.** That is where a terminal already puts transient key hints — a
  `tmux` status line, `fzf`'s own — and it is where `checklist.py` was already closest
  to putting one. Dim is `ui.detail`'s tone, the same one every secondary line in lane
  uses. There is no smaller font in a terminal, so *quieter* is styling and brevity,
  and nothing else: the shortest wording that still says what the screen's keys do.
- **One line, never two.** A screen with more to say says it in one more clause of the
  same tiered line, which then sheds in the order §13 gives.
- **A screen with no keys of its own draws nothing** — `text` and `confirm`
  (`picker.TEXT_KEYS`), which is what they already drew (§2). Stated as an empty key
  set rather than as an absence in two files, so the rule has no exceptions to keep.

## 4. Menu and list entry wording

- **Lower-case, one word where possible, noun for a destination, verb for an
  action** — `open`, `list`, `settings`, `doctor`, `quit`; `enter`,
  `close` for the two things you can do to a lane. Keep doing this.
- **`list` is the one entry that breaks the noun/verb half of that rule, and it was
  decided rather than slipped in.** It was `lanes`, which was a perfectly good
  destination-noun. It is now also a subcommand, and a subcommand has to be `list`
  because that is what `git`, `gh`, `docker` and `kubectl` all call it — so the choice
  was between one screen with two names and one entry that reads as a verb. §14 wins:
  **one term per concept** is the rule a reader meets every time, and the part of
  speech is a rule they meet once. `open` is the existing precedent — a verb-shaped
  entry to a destination that has never confused anybody. The full argument is in
  AGENTS.md; do not "fix" this back without reading it.
- **The hint/description after an entry is a plain sentence fragment, not
  restating the entry's own word**: `"Every open lane, where it stands, and what to
  do with it"`, not `"Show the lanes"`.
- **Hints align to a common column**, the width of the longest label in that list,
  the same way the lanes table already aligns its columns. *Why: a fixed
  three-space gap was the one thing in the app's own README that no longer matched
  what was on screen.* Fix in
  `picker.py`'s `pick()`: compute the longest `option.label` once, `ljust` before the
  gap.

## 5. Symbols

The set, and only meaning each one carries:

| Symbol | Means | Where |
|---|---|---|
| `✓` | this step or lane-fact succeeded / is fine; **and** this checklist row is *in* — a leaf, or every path under a folder | `ui.ok`, table `✓ merged`, `checklist.py` |
| `✗` | refused / failed; **and** this checklist row is *out* — deliberately kept out of the lane | `ui.error`, `checklist.py` |
| `○` | **nothing** this checklist row stands for has been answered yet | `checklist.py` |
| `?` | **something** under this checklist folder is still unanswered | `checklist.py`, folder rows only |
| `◐` | this checklist folder is fully answered and its paths disagree — some in, some out | `checklist.py`, folder rows only |
| `!` | worth your attention, not yet blocking or already handled | `ui.warn` |
| `●` | count of uncommitted/untracked files | table `state` cell |
| `↑` | count of unpushed commits | table `state` cell |
| `❯` | the cursor, in any picker or the table | `picker.py`, `table.py` |
| `←` | this entry leaves the current screen **backwards** | `← Back`, `← Back to the menu`, `← Back without entering` |

**`✓` and `✗` each carry a second meaning rather than a second glyph.** On the checklist
`✓` marks a row that comes into the lane and `✗` one deliberately kept out. Extending the
two was chosen over inventing more (`[x]`, `●`, `▸`) because the set is small on purpose,
and because in both cases the second meaning is the same family as the first — *this is
fine* / *this one is in*, *refused* / *this one is refused*. Colour is not what says it:
which mark is present is (§6).

**`✗` widening was a deliberate reversal, and the reason it is now right is that
something changed.** *Out* used to be the **absence** of a mark, and that was defensible
while a row had two answers — until a third arrived. With three, an absent mark had to
carry both *out* and *not yet asked*, which are opposite things: one is a decision and the
other is a question still open. `✗` for the decision and `○` for the question is what
makes them tellable apart at all.

**`○`, `?` and `◐` are the checklist's own three, and a folder row is the whole reason
for the last two.** A leaf has three answers and `✓`/`✗`/`○` says all of them. A folder
stands for every path beneath it, which can additionally be *partly unanswered* or
*fully answered and disagreeing* — and those are different facts, only one of which the
user still has to come back to, so they cannot share a glyph. `?` is deliberately **not**
another circle: `○`/`◐`/`✓`/`✗` all answer *how much of this is in*, and `?` answers *is
there still a question in here*, so a fifth fill level would be read as the wrong kind of
answer and mistaken for `◐`. Being the one non-circle is what makes it tellable apart by
shape rather than by colour (§6), which matters because three of the five are drawn
`warn`. The row's panel says it again in words.

**`←` marks going back, not going on.** A checklist level **inside a folder** has a
`← Back` row, because unlike the root it has somewhere to go back *to*: one step back, so
the plain label, exactly as every `choose` prompt uses it. The **root** has none, having
nothing above it. Both levels do have the two rows that go *on* — `apply` and `discard` —
and those take no arrow: `←` is for the row that leaves **backwards**, and neither of
those does.

**A new screen uses one of these, for the meaning above, or none at all — it does
not invent a new symbol.** If a screen needs to say "sub-item of the line above",
use a two-space indent with no marker (settings, doctor, the close summary) — not a
bullet. *Why: the changelog screen's `•` used to be the one place a bullet
appeared, for a job every other screen does with indentation alone — it was
dropped to match, and the screen itself has since gone (AGENTS.md, "Releasing").*

**A terminal without the symbol font**: not tested live in this audit (out of scope
for a presentation-only pass — would need faking the terminal's font capability,
which lane has no seam for). If this becomes a real complaint, the fallback is
ASCII per symbol (`v`/`OK`, `!`, `x`, `*`, `^`, `>`, `<-`) behind a capability check,
not a silent swap — flag as its own decision if raised.

## 6. Colour

**Decided already, cited not restated**: a cell's `Tone` (`""`, `good`, `warn`,
`bad`, `dim`) is what it *means*, and the widget decides what colour that is
(`seam.py:42-43`) — actions never choose a colour directly. **Colour never carries
meaning alone**: every toned cell already restates its meaning in the text itself
(`✓ merged`, `not merged yet`, `unknown`, `detached · …`). Keep this: a new tone
value or a new toned cell must have a
plain-text tell alongside the colour, checkable by someone reading a
colour-stripped transcript.

## 7. Settings — as a worked example

The old shape was an unconditional sequence of three questions, identical on a
first run and a tenth, with no per-setting entry and no visible way to stop
partway. The current shape matches how every other multi-item screen in this app
works — a list you act on, not a fixed script:

```
lane settings
  <config path>

  setting              current value
❯ projects root        /Users/you/Projects
  lanes root           /Users/you/Lanes
  editor               cursor
  preparation          4 paths in, 2 out
  commands             1 step
  branch prefixes      6 prefixes
  ← Back to the menu

  ↑↓ move · enter choose
```

`preparation`, `commands` and `branch prefixes` are rows four, five and six and **not
settings**: they are destinations, so they are nouns (§4), and their value cells say what
is there the way the others say what they are set to. Both cover every project on one screen rather than a
project list and then a page each — the lanes table already draws rows from several
projects in one table with a dimmed `Cell.lead`, so a third level of nesting is
unnecessary. Back labels stay scoped as ADR 0002 requires: `← Back to the menu` here,
`← Back to settings` there.

**`preparation` opens the very screen entering a lane opens** — `Ui.check` over the same
rows, answered with the same keystroke. That is one component with two callers, not two
screens that resemble each other, and the difference matters because resemblance drifts:
this pair had already drifted into a checklist on one side and `Enter` → *change* → pick-a-
verb on the other, three screens to move one path. What the two callers pass differs in
exactly two ways, both data: settings leads each row with its project, and entering has a
lane in hand so it can say which paths are already in it.

**`commands` is separate because a command is not a path.** It is typed rather than
discovered and carries a directory and a guard to edit, none of which is a checkbox — so it
keeps the list you act on one row of, with `change`/`forget` exactly as the lanes table
offers `enter`/`close`.

**`branch prefixes` takes that same shape rather than inventing a third one.** A prefix is
typed rather than discovered, and it is one string rather than an in-or-out answer, so it
is not a checkbox either: its own list, `change`/`forget` on the row under the cursor, and
`add a prefix` appended the way `← Back` is. Its second column is the branch the prefix
would make (`feature/<lane>`), dimmed — the row's own name says what it is called, and the
example says what choosing it does. **Its rows are never sorted**: the order is what the
branch prompt shows, and putting the one you reach for most at the top is the only thing
ordering it can be for — which is also why `change` renames in place rather than dropping
the row to the bottom. It never says `nothing yet`, because there is always at least one
(AGENTS.md, *The branch prefixes*); forgetting the last one puts the six back and **says
so**, since six rows silently reappearing reads as the forget having failed.

Choosing a row asks that **one** question (with today's validation — a projects root
with no repositories is still refused, a lanes root inside the projects root still
warns) and returns to this list, updated, rather than to the menu — the same
"looking and acting are the same widget" rule the lanes table already follows, and
for the same reason: re-deriving a settings-list-then-separate-question flow is
exactly the fault ADR 0002 fixed for lanes.

**First run** (no config file yet) is the one case that still wants the fixed
sequence: there is no "current value" list to show, and nothing works until all
three are set. So: no config on disk → today's three-question walk, unchanged,
ending by writing the file. Config already on disk → the list above. This is a
one-time branch on `store.path.exists()`, not two permanent code paths to keep in
sync — the list screen's per-row question *is* the sequence's question, just asked
one at a time.

Implementation: `src/lane/actions/settings.py`. `run()` branches once on
`context.config_store.path.exists()`; `_run_first_time()` is the old sequence,
unchanged; `_run_list()` is the new screen, built on `Ui.browse()` exactly like
the lanes table. Both call the same `_ask_projects_root`/`_ask_lanes_root`/
`_ask_editor` functions, so validation exists in exactly one place. An
environment override shows as a note on the affected row and in its detail panel
when the cursor is on it — at least as visible as the old banner, per-setting
instead of all-at-once.

## 8. Question and confirmation phrasing

- **A question is a complete sentence fragment ending where a colon would go**, no
  trailing `?` inside `text` titles (the picker widgets add their own punctuation
  structurally: `text` appends `: `, `confirm` appends `[y/N] `) — e.g. `"Which
  folder do your projects sit in"`, not `"Which folder do your projects sit in?"`.
- **A default is shown in brackets, immediately after the question**: `[y/N]` /
  `[Y/n]` for a yes/no default, `[<current value>]` for a text default. One bracket
  convention, wherever a prompt has a default.
- **A confirmation is a complete question a user could answer out loud**: `"Enter
  that lane instead?"`, not `"Confirm?"` or `"Proceed?"`. When the action is
  destructive, the warnings printed immediately above it (already the pattern in the
  close flow) are what signals that — a confirmation's own wording does not need to say
  "permanently" or "cannot be undone"; the findings above it already said what's at
  stake.
- **The same rule reaches a row on a screen, and that is where it bit.** The close's
  rows say what closing does — `delete branch feature/x` — and the `!` line above says
  it is not merged. They used to read `Delete it anyway?`, and "anyway" was the wording
  answering a question the warning had already asked: a second telling, in the one place
  this rule says not to put one. A row is a verb phrase for the same reason a
  confirmation is a whole question — say what will happen, once.

## 9. Reporting outcomes

**Already consistent; keep doing this.** Every action ends by saying what happened,
in the `ok`/`warn`/`error` shape: `✓ <what succeeded>`, `! <what's kept/partial>`,
`✗ <what failed>: <why>`. A failure that can be fixed names the fix in a `detail`
line underneath, indented two spaces. Success and failure share this shape by
construction (one seam, `console_ui.py:140-149`) — a new action gets this for free
by using `ui.ok`/`warn`/`error` and must not print its own ad hoc success/failure
line.

## 10. Waiting

**Already consistent; keep doing this.** Exactly one mechanism —
`ui.progress(text, work)` — for any step slow enough to need one: a `rich` spinner
with the dimmed description of what's happening, phrased as a gerund with an
ellipsis (`"Fetching origin…"`, `"Asking GitHub about the pull request…"`,
`"Reading lane status…"`, `"Removing the worktree…"`). A new slow step uses
`progress`; it does not print `"Please wait"` or roll its own spinner.

- **The steps after the last question need this most, not least.** A wait with a
  prompt still on screen is legible; the pause between `y` and `✓ Lane closed` is
  not, and it is the longest one lane has. *Why: this was previously unstated, and
  the close's whole removal phase ran silently as a result — the one place the tool
  looked hung was the one place it was working hardest.*
- **One spinner per user-visible action, not per subprocess.** Pruning is
  bookkeeping belonging to the removal, so it shares its spinner; deleting the
  branch is its own step and gets its own. Preparation gives one to each step it
  applies (`"Cloning apps/web/node_modules…"`), and the staging and swapping inside one
  clone share it.
- **A step that is not slow gets none.** Preparation's discovery runs on the way to the
  editor *every* time a lane is entered and is 15 ms on a twelve-thousand-file
  repository — a spinner there would flash on the hottest path in the application, and it
  would be the only thing standing between an already-prepared lane and costing nothing
  visible. `progress` is for a wait, not for a receipt.
- **Ctrl-C during a spinner backs out**, exactly as at a prompt — with the single
  exception of a close's removal phase, which defers it. See *Ctrl-C is answered
  everywhere* in AGENTS.md before adding a second exception.

## 11. Errors and refusals

- **A refusal names what's wrong and, where there's a fix, the exact command or
  screen that applies it** — already the pattern (`"Fix it with: brew install gh"`,
  `"Point the projects folder at <path> in settings"`).
- **The rule for whether a refusal returns to the menu or ends the session**: it
  ends the session only when the session itself cannot start (the config file
  couldn't be read at all — there is no menu yet to return to). Every other refusal,
  including "git is not installed" and every action-level error, returns to the
  menu. *Why: this asymmetry is defensible but was previously unstated — this is
  now the stated rule a new failure mode should be checked against.*

## 12. Empty states

- **One line, in the same `ui.detail`/`ui.error` shape as everything else, naming
  the next action by its current menu name.** `"No open lanes. Open one from the
  menu."` is the reference. When something renamed, the empty-state text is one of
  the places to grep for the old name — it's exactly the kind of text that outlives
  what it describes.
- **A subcommand's empty state names the subcommand, because it has no menu to point
  at.** `lane list` with nothing open says `"No open lanes. Open one with: lane open"`.
  Same rule, not an exception to it: name the next action *as this caller would reach
  it*. Telling somebody in a pipe to choose something from a menu is the fault the rule
  exists to stop, one layer out.
- **No table, no header, no cursor for an empty list.** Already the rule for the
  lanes table (ADR 0002) and worth stating generally: a screen built around a list
  does not render the list's frame when the list is empty.
- **This governs the *data* rows.** An action row — the visible way back, or settings ·
  preparation's `add a step` — survives an empty list, because a screen whose only purpose
  is to let you add the first item cannot answer with a line of prose. *Why: previously
  unstated, and the two readings differ exactly where it matters — on the screen you reach
  when there is nothing there yet.*
- **A filter that matches nothing is one of these**, not a frozen table with nothing in
  it: `No matches for '<filter>'.`, drawn where the filter's own `<n> of <total>` line
  would be, with no header and no rows under it and the screen's action rows still there
  (§3). The line names the filter because backspacing it is what undoes it.

## 13. Width and truncation

- **What gives way, in order, is always: whole low-priority columns first, then a
  repeated/redundant prefix, then the primary identifier — and never the column(s)
  that answer the screen's actual question.** This is the lanes table's rule
  (`table.py:22-28`) stated generally so a second table can be checked against it.
- **A truncated identifier gets a single-character ellipsis (`…`) at the cut, on one
  line — never a mid-word wrap across two lines.** This is the table's `_clip`
  behaviour, and the rule for any `rich`-rendered long token (a path) too. **Built —
  Phase L, box L6**: `render.clip_long_words()` clips only a single word wider than
  the console (a path has no spaces, so it's one long word); ordinary prose keeps
  wrapping at its spaces exactly as before. Wired into every `ConsoleUi` telling
  method via `_clipped()`. *(An earlier attempt used
  `Console.print(..., overflow="ellipsis", no_wrap=True)` globally — rejected in
  review because it also stopped long prose sentences, like a doctor remedy, from
  wrapping at all instead of only fixing the path case; `clip_long_words` is
  narrower on purpose.)*
- **A column that answers the screen's own reason for existing is never dropped and
  never truncated, at any width the screen actually promises to support.** This is
  the stated invariant for the lanes table's `state`/`pr` (ADR 0002). On the checklist it
  is the **mark** (`✓`/`✗`/`○`/`?`/`◐`), which is a gutter rather than a column and so
  cannot be dropped at all. What gives way there, in order: `in lane` (the cursor panel says the same
  thing in words, so nothing is lost that cannot be got back), then `size` (which nothing
  repeats), then the dim `Cell.lead` — which on a level inside a folder is the directory
  every row on it shares and therefore identifies nothing — then the path truncates.
  **The footer degrades too rather than being clipped** — `footer.tiers()` gives up the
  arrows first, because nobody needs telling that arrows move, then what each key does,
  and keeps the keys themselves; the scroll position goes before any of the hint does.
  That is now every screen's footer rather than the checklist's alone (§3a). It no
  longer names `ctrl-c` at any width: the way out is the `discard` row, which is visible
  in the way §2 actually asks for. **Built —
  Phase L, box L7, decision: abbreviate `state` before `pr` is ever endangered.**
  `Cell` (`seam.py`) gained a `short` field; `table.py`'s `_fit()` switches every
  cell to its short form, if it has one, before ever shrinking the lane-name column
  — `state`/`pr` are still never truncated or dropped, just measured against
  shorter text first. Chosen abbreviations (`list_lanes.py`'s `_state_cell()`):

  | Long form | Short form |
  |---|---|
  | `● N uncommitted` | `●N` |
  | `↑ N unpushed` | `↑N` |
  | `● N uncommitted · ↑ N unpushed` | `●N ↑N` |
  | any of the above combined with `✓ merged` | append ` ✓` (e.g. `●N ↑N ✓`) |
  | `detached · <state>` | `detached <short-state>` |
  | `no commits yet` | `no commits` |
  | `not merged yet` | `not merged` |
  | unreadable / problem text | `unreadable` (the one case that loses detail — the long form is arbitrary free text) |

  `tests/test_table.py` and `tests/test_screen_snapshots.py` cover this at 40–44
  columns using the **combined** state string, closing the coverage-floor gap that
  let the original regression through.

## 14. Vocabulary

One term per concept. The list, and the survivor where two forms were found:

| Concept | Use | Not |
|---|---|---|
| The unit of work (worktree + branch + editor window) | **lane** | task, workspace |
| The git primitive a lane is built from | **worktree** | (used deliberately alongside "lane" — see AGENTS.md; not interchangeable, both needed) |
| Leaving a prompt without answering | **back** / **back out** | cancel, abort, quit (that word is reserved for the menu's own exit) |
| A setting currently coming from the environment, not the file | **overrides** | present tense, matching between doctor and settings — it reads as the current fact, not a description of an ongoing process |
| The three-question setup screen | **settings** | config, preferences, setup (used once, for the very first run, and even then it's the same screen) |
| Bringing what `.gitignore` hides into a lane, before the editor opens | **preparation** (verb: **prepare**) | setup, bootstrap, provisioning, sync, hydrate, seed |
| One remembered decision — a path or a command, and what lane does with it | **step** | entry (reserved for a menu or list row), rule, item, recipe |
| What lane does to a path | the **verb** — `clone`, `run`, `skip` | action (reserved for a menu action, `ACTIONS`, `actions/`); `link`, which was a verb and is not any more |
| A path's answer, as the user sees it | **in** / **out** (of the lane) | on/off, included/excluded, yes/no, selected |
| A path nobody has answered yet, on screen or in the store | **unanswered** (adjective: a row is *not yet answered*) | unset (used in the source for the third state, not on screen), unknown, pending, undecided, skipped (that is `out`, and the two are the whole point) |
| Ending the checklist and recording what was decided | **apply** | accept, save, done, confirm, ok |
| Ending the checklist and recording nothing | **discard** | cancel, abandon (used in the source for `Abandoned`, not on screen), abort, reset |
| Ending the close screen and doing what its rows say | **close** | apply (the checklist's word for a different thing), confirm, proceed, yes, remove |
| Ending the close screen and touching nothing | **leave open** | discard, cancel, keep, no, abort |
| Leaving lane altogether with Ctrl-C | **quit** — the same word the menu's own entry uses, because it is the same door | exit, kill, interrupt (reserved for one that landed while lane was *working*) |
| Ignored paths under one directory, shown as one row you can go into | a **folder** (of paths) | group (used in the source for the type, not on screen), bundle, batch, directory (git's word for the thing on disk, not for the row) |
| A folder row whose paths are not all answered the same way | **mixed** (`◐`) | partial, some, indeterminate, half |
| A path already in the lane, which a tick therefore leaves alone | **already there** | present, exists, installed |
| The listing, as a thing you choose | **list** — the menu entry and the subcommand, one word | lanes (the old entry name; still the right word for *the lanes table* as a screen, and for `lanes_root`) |
| Answering a prompt from the command line before it is drawn | the flag **answers** the question | pre-fill, inject, mock (a mock replaces; this answers) |
| The two things opening a lane can mean | **new work** / **existing branch** | new/existing alone (they name nothing), fresh, scratch, checkout |
| A branch that was already there when the lane opened | the lane **adopted** it (adjective: **adopted**) | borrowed, reused, attached, imported |
| A branch that came into being with or during the lane | the lane **created** it | own, new, made |
| Narrowing a list to what matches what you typed | **filter** (verb: *filter*; the text is *the filter*) | search, find, query, fuzzy — and *hint*, which already names the description after a menu entry (`Choice.hint`) |
| The dim line in the bottom-right of a screen naming what its keys do | the **corner hint**, rendered by `ui/footer.py` (`footer` in the source, `class:table.footer`) | status line, legend, help bar |
| The `feature`, `bugfix`, `spike` part in front of a branch name | a **prefix** (screen: **branch prefixes**) | namespace, category, type, kind (reserved for what a lane is *for*, `KIND_QUESTION`), scope |
| The prefixes lane offers before anybody customises them | the **seed** (the **six** lane ships with) | default (used in the source for `DEFAULT_PREFIXES`, and already taken by *default branch*), built-in, factory, preset |

**prefix** is the whole term, and the screen is plural where the concept is singular:
one row is a prefix, and *branch prefixes* is the menu of them. **The word never stands
alone in a heading** — `lane settings · branch prefixes`, not `lane settings · prefixes` —
because a bare `prefix` in this application could as easily be `Cell.lead`, which is also a
dim thing in front of a name.

**seed** is worth its own row because *default* is already spoken for twice over: the
**default branch** is a git fact lane asks `origin/HEAD` about, and `Config.with_defaults`
fills in a value per setting. The prefixes have neither shape — they are one list that is
either customised or not — so calling the untouched list the seed keeps all three
tellable apart. `DEFAULT_PREFIXES` stays the source's name for it, the way `unset` stays
the source's word for *unanswered*.

**adopted** and **created** are worth a row each even though nothing on screen says
either word: they are how AGENTS.md's *"branch deletion applies to the lane's own
branches"* is now read, and a session reaching for "borrowed" or "reused" in a
comment would be describing the same distinction in a second vocabulary.

`verb` is no longer a column header anywhere: the preparation screen asks in-or-out and the
tick answers it. The word still names the concept in the source and in `prepare.Verb`, for
the reason it always did — AGENTS.md calls `enter` and `close` "the two verbs" the lanes
screen offers, and `action` would collide with the only other thing in the application that
word names.

**`mixed` is back, and it is a mark rather than a word.** A folder whose paths were
answered differently once read `mixed` in a verb column; then the verb column went and a
checkbox, having two states, could not say it — so such a folder was not folded into one
row at all, and was drawn as its own rows instead. That was truthful and it was also the
flat screen this drill-down replaced. `◐` says it in the gutter where the answer already
lives, so the folder keeps its row and the word stays out of the columns: on screen the
mix is a mark, and `mixed` is what to call it in prose, a commit message or a comment.

**`unanswered` in prose, `unset` in the source, and never *skipped*.** The third state is
the one this vocabulary is easiest to get wrong in, because the wrong word is already
taken: a `skip` step is a path the user answered **out**, and calling an unanswered path
"skipped" collapses exactly the distinction the third state exists to draw. In prose and
on screen a row is *not yet answered*; `unset` is the source's word for the absent key in
`Answers`, and `UNSET` names the mark that draws it.

If a new screen needs a term not in this table, add it here in the same change —
this table is the thing to grep before reaching for a synonym.
