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
  lanes table is the one exception, and it's deliberate: its title *answers* "what
  am I looking at" (`"3 open lanes in demo"`) rather than repeating the word "lanes"
  — see ADR 0002. A new screen gets a heading unless it is, like the table, a screen
  whose title can say something more useful than its own name.
- **One blank line between logical groups of output, none within a group.** A
  "group" is: the heading and its immediate context; each self-contained check or
  question; the final outcome. Doctor's tool checks, settings' three questions (no
  blank line *between* them — they are one flow), and the close summary's findings
  vs. its "About to remove" block are the reference shape. *Why: the three report
  screens were close to this but not identical, with no written rule to check a
  fourth screen against — this is that rule.*
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

**This visibility requirement applies to `Ui.text` and `Ui.confirm` too**, which
otherwise have no visible exit and rely solely on an unannounced Ctrl-C.

- Every `text` and `confirm` prompt renders a **dim footer hint**, the same way
  `choose`/`browse` already do, naming the one way out: `ctrl-c back out` (or fold
  into the existing per-widget `HINT` constants so there is exactly one hint string
  per widget type, not per call site).
- This is a **presentation change, not a behaviour change**: it does not bind a new
  key or alter what Ctrl-C already does. It makes the existing behaviour visible,
  which is the whole point of the rule it's closing the gap on.
- Do not add a rendered `← Back` *entry* to `text`/`confirm` — there is nothing to
  choose between; a footer hint is the right amount of visibility for a prompt with
  one exit, not a picker with an extra row.

## 3. Key bindings

**Fully decided in AGENTS.md and `picker.py`; cited, not restated.** The whole
vocabulary: `↑` `↓` `Home` `End` move, `Enter` chooses or accepts, `y`/`n` answer a
yes/no question, `Ctrl-C` backs out, everywhere. No `q`, no vim keys, no digit
shortcuts, no Esc — each removed on purpose, with the reasoning kept in
AGENTS.md's "Going back is visible" section. **A new screen introduces no key this table doesn't already
have.** If a screen seems to need one, that is a decision for the maintainer
(AGENTS.md says so explicitly), not a convenience to slip in.

The one place this table is currently *misrepresented* rather than violated: fix per
§9 below.

## 4. Menu and list entry wording

- **Lower-case, one word where possible, noun for a destination, verb for an
  action** — `open`, `lanes`, `settings`, `doctor`, `quit`; `enter`,
  `close` for the two things you can do to a lane. Already consistent; keep doing
  this.
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
| `✓` | this step or lane-fact succeeded / is fine | `ui.ok`, table `✓ merged` |
| `!` | worth your attention, not yet blocking or already handled | `ui.warn` |
| `✗` | refused / failed | `ui.error` |
| `●` | count of uncommitted/untracked files | table `state` cell |
| `↑` | count of unpushed commits | table `state` cell |
| `❯` | the cursor, in any picker or the table | `picker.py`, `table.py` |
| `←` | this entry leaves the current screen | `← Back`, `← Back to the menu` |

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
  ← Back to the menu

  ctrl-c back out
```

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
- **A confirmation is a complete question a user could answer out loud**: `"Close
  it?"`, not `"Confirm?"` or `"Proceed?"`. When the action is destructive, the
  warnings printed immediately above it (already the pattern in the close flow) are
  what signals that — a confirmation's own wording does not need to say
  "permanently" or "cannot be undone"; the findings above it already said what's at
  stake.

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
`"Reading lane status…"`). A new slow step uses `progress`; it does not print
`"Please wait"` or roll its own spinner.

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
- **No table, no header, no cursor for an empty list.** Already the rule for the
  lanes table (ADR 0002) and worth stating generally: a screen built around a list
  does not render the list's frame when the list is empty.

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
  the stated invariant for the lanes table's `state`/`pr` (ADR 0002). **Built —
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

If a new screen needs a term not in this table, add it here in the same change —
this table is the thing to grep before reaching for a synonym.
