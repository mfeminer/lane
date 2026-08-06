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

## The interaction model — no subcommands

`lane` accepts exactly two arguments: `--version` / `-V` and `--help` / `-h`.
Anything else is an error that says so. **There are no subcommands and no command
aliases.** Running `lane` bare starts an interactive session:

- it shows a menu of everything lane can do
- you choose an action and lane walks you through it with prompts
- when the action finishes you are back at the menu
- the session ends when you choose to quit

**Do not reintroduce subcommands**, however convenient a `lane open` shortcut
looks: two entry points would mean two things to keep in step, and the menu is the
one that matches how the tool is actually used (twice a day, from a shell you are
not scripting). `--version` and `--help` are flags rather than menu entries
because they exist for people who have not started the app yet.

There is no `where` action to print a lane's path for shell integration
(`cd "$(lane where)"`). The four-step day above never needs it. Do not reintroduce
it as a shell-integration hook or a clipboard action.

Actions: open a lane, lanes, settings, doctor.

There is no `changelog` action. It was one until the release notes became
generated from the merged pull requests rather than written by hand: keeping the
screen would have meant shipping a second copy of those notes inside the binary,
which is the duplication the whole release change exists to remove. What changed
in a release is on its GitHub release page. Do not reintroduce it — see
*Releasing* below. (**`docs/adr/0002-lane-listing.md`** predates this and still
lists the menu with `changelog` in it; it is a record of that decision, not the
current menu.)

**`enter` and `close` are not menu entries.** They are the two verbs the `lanes`
screen offers for the row under the cursor — see **`docs/adr/0002-lane-listing.md`**
and *The lanes screen* below. Do not put them back as separate menu entries: both
used to begin by asking *which lane* from a picker showing the same names with none
of the status, which is a worse route to the same place. This is not the same thing
as hiding an entry behind an unmet prerequisite, which stays forbidden.

Consequences that are load-bearing:

- The menu is generated from **one table**, so it cannot drift from what the app
  can actually do. The menu is always the full list: prerequisites are enforced
  where they are used, never by hiding or greying out entries.
- lane **requires a TTY**. If stdin or stdout is not a terminal, print a clear
  message saying lane is interactive and exit non-zero. No half-working
  non-interactive fallback. `--version` and `--help` are the exceptions and must
  work anywhere, including CI.
- There is **no machine-readable output**: no JSON, no parseable listings, no
  careful stdout/stderr split. Write for a human sitting in front of the session.
  Exit codes are the one exception and stay meaningful — 0 for a clean exit,
  non-zero for a refusal or failure.
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
| `Ctrl-C` | back out |

**That table is the whole vocabulary.** It describes Ctrl-C *at a prompt*; what it
does while lane is **working** is below, under *Ctrl-C is answered everywhere*. A letter key for "close" was considered and
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

### Ctrl-C is answered everywhere, and means three different things

The structural guarantee above covers prompts. Ctrl-C can also arrive while lane is
*working*, where there is no prompt to catch it, and **nothing lane does may end in
a traceback** — that is the one outcome a user can do nothing with. Three zones,
and which one a new step is in is a question worth asking deliberately:

1. **While a spinner is up, before anything irreversible** — fetching origin,
   asking GitHub, reading lane status. Identical to backing out of a prompt:
   `ConsoleUi.progress` turns the interrupt into `Abandoned` and the screen you
   were on comes back, silently. Nothing had happened yet, so nothing is said.
2. **During a close's removal phase** — the one stretch where stopping half-way is
   worse than either finishing or never starting. A partly deleted working copy,
   or a lane whose worktree is gone but whose branch and metadata survive, is a
   state nothing in lane can describe, let alone repair. So the interrupt is
   **deferred** (`lane.interrupts`): acknowledged on screen the moment it lands,
   raised once the phase is done. A second Ctrl-C is never deferred — it means
   *now*, and the acknowledgement says so. This needs `start_new_session` on git
   subprocesses to mean anything (see *The git backend*).
3. **Anywhere else** — the session reports it in one line, says a step already
   under way may be half-done, names `lanes` as the screen that shows where things
   stand, and returns to the menu. `cli.main` is the backstop underneath all of
   this and exits `130`.

Zone 2 is the **only** place an interrupt is deferred, and it is deferred because
its questions are all behind it — not as licence to defer one elsewhere. If a new
step wants deferral, check first whether it is really asking for its questions to
be moved earlier.

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
  keep all of it, and one sentence about the pull request. **It never makes a git
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
  fast and is collected before the screen appears; `gh` is a process per lane and
  is not, so the `pr` column opens as `checking…` and fills in behind the screen you
  are already using. If the listing blocks on a `gh` round trip, this is broken.
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
- **`unknown` and `none` are different answers.** `none` means GitHub was asked and
  said no; `unknown` means it could not be asked, and the panel names the command
  that fixes it. This is the one thing the close flow can never tell you, because
  for such a lane it refuses before it gets that far.
- **After closing you stay in the listing**, one row shorter, with the cursor on
  the row that took the closed one's place; pull request answers already paid for
  are kept, so the second paint is immediate. **After entering a lane you go back to
  the menu** — your attention has moved to the editor, and the listing's data is
  about to go stale. The asymmetry is deliberate: closing repeats, entering does not.
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
  question: **what is the state of the pull request for this branch?** Its answer
  includes "I cannot tell you, because `gh` is missing or logged out" as a
  first-class result. The close path decides from that answer alone and **never
  probes the environment separately**. Today it shells out to
  `gh pr view <branch> --json number,state,url`; tomorrow it might be an HTTP
  call, and the rest of the application must not be able to tell.
- The check does not apply to non-GitHub remotes or to lanes on a detached HEAD:
  there is no pull request to ask about, so those closes proceed on git's own
  evidence and never touch `gh`.
- A `MERGED` pull request **counts as clean even when git's ancestry check
  disagrees**: a squash or rebase merge leaves the lane's commits nowhere in the
  default branch, and resolving that false negative is the entire reason this
  feature exists. `OPEN` and `CLOSED` are blocking issues, each reported with its
  URL; "no pull request found" is a blocking issue without one.
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
| `GitBackend` | all git access (subprocess to `git`) | **No.** Real backend, temporary repositories |
| `GitHubClient` | pull request state | Yes — the suite never authenticates or touches the network |
| `Environment` | TTY-ness, tool presence on PATH, launching the editor | Yes — this is what lets the suite run under pytest without a TTY and without opening an editor |
| The prompt layer (`Ui`) | everything that asks the user something, and everything it tells them | Yes — replays scripted answers, records what was said |

`GitBackend` exists so the implementation can be **swapped**, not so tests can
avoid git. Tests use the real one against temporary repositories.

`Environment` reports tool presence **for doctor's benefit**; it does not decide
whether a close may proceed — that comes from `GitHubClient`'s answer. The TTY
refusal is tested by faking `Environment`, never by manipulating the real terminal.

The seam is called **`Ui`** and it both asks and tells. Output belongs with asking
rather than in a fifth injected thing: both are presentation, an action needs both,
and the progress indication for a long step ("Fetching origin…") is telling. So
`Ui` carries `choose`/`text`/`confirm`/`browse` alongside `info`/`ok`/`warn`/
`error`/`detail`/`heading`/`blank`/`progress`.

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

**One action catches it, and only one.** The listing catches `Abandoned` — around
the per-row verb menu, and around the close it launches — so that backing out of
either returns to the table rather than to the main menu; the table is a screen you
are standing in. Both are safe for exactly the same reason as everywhere else:
every question still comes before the first irreversible step, so an abandoned verb
menu or an abandoned close has changed nothing. The close is included because
Ctrl-C during its fetch is Zone 1 above, and throwing away the screen the keystroke
happened on would punish impatience with a lost place. Do not take this as licence
elsewhere; if another action wants it, it wants a screen.

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

**The lanes table is the same kind of component and gets the same treatment** —
`ui/table.py`, below the seam, with `tests/test_table.py` driving it through pipe
input. Its layout is a pure `paint(…, width, height)` returning the lines it would
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

**A single candidate is auto-selected without prompting, and bad input re-prompts
instead of aborting.** In a windowed picker "re-prompts" means an unrecognised key
is ignored and the picker stays up — it never aborts.

**A yes/no question is a real `y`/`n` confirm, not a two-option picker.** Labelling
a prompt `[y/N]` and then refusing to accept `y` is worse than either option alone.

## Invariants — each with its reason

These must never regress. Each is one line of behaviour and one line of why.

- **New branches are created with no upstream** — so a bare `git push` inside a
  lane can never land on the default branch.
- **Commits on a detached HEAD are parked on `wip/<lane>` before removal, and that
  branch is never deleted** — deleting it would defeat the entire purpose of the
  rescue.
- **Branch naming is decided per lane, not globally** — one lane can be `bugfix/…`
  while the next is `feature/…`; it is a property of the task, not of the machine.
- **Lane and branch names are always plain ASCII** — task descriptions are typed
  in whatever language the user thinks in; paths and refs must not be.
- **The config upgrade notice stays one short line** — what a release changed is
  on its GitHub release page, and an upgrade notice must not become a changelog
  dump.
- **Doctor is always reachable, no matter which prerequisite is missing** — it is
  the action that explains missing prerequisites.
- **The rest of the menu is never gated behind a missing `gh`** — only closing a
  GitHub-backed lane needs it.
- **A TTY is required**, `--version` and `--help` excepted — there is no
  half-working non-interactive mode to maintain.
- **Going back is a visible entry, never only a key** — `← Back` in every choice
  prompt, a `← Back to the menu` row at the end of the lanes table, `quit` at the
  menu. A key a user has to be taught is a key that should not exist.
- **Looking at a lane and acting on it are the same widget** — a table you read
  followed by a prompt that re-lists the same lanes makes the reader match a row to
  an action by eye, and grows as lanes × verbs.
- **The lanes screen binds no key the picker does not** — arrows, `Enter`,
  `Ctrl-C`. A letter key for a verb would be this tool's invention, however visible
  the legend.
- **The listing never blocks on `gh`** — git status is collected before the first
  paint, pull request state fills in behind it. It is the difference between a
  screen that appears and one that appears two seconds later.
- **The listing's `pr` column distinguishes "asked and there is none" from "could
  not ask"** — `none` and `unknown` mean opposite things, and only one has a remedy.
- **The listing's row order never changes while it is on screen** — a cursor over
  rows that rearrange themselves is worse than no cursor.
- **Escape is not bound at all** — eagerly it swallows Option+Arrow; normally it
  takes over a second to register. Neither is acceptable and neither is needed.
- **Ctrl-C never surfaces as a traceback, wherever it lands** — a stack trace is
  the one outcome a user can do nothing with. At a prompt it backs out, during a
  spinner it abandons, during a close's removal it is deferred and then reported,
  and `cli.main` exits `130` under all of it.
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
- **The lane's starting commit is recorded in its metadata** — it is the only thing
  that distinguishes "has done no work" from "work has landed"; both leave nothing
  ahead of `origin/<base>`.
- **Path identity is asked of the filesystem, never compared as strings** —
  `samefile`, not `resolve() == resolve()`. macOS and Windows are case-insensitive,
  so `/users/me/projects` and `/Users/me/Projects` are one directory while their
  resolved strings differ; comparing strings once made every project vanish.
- **`find_nested_repository` and `list_projects` use the same definition of
  "repository"** — when they disagreed, lane reported "no projects here" and then
  suggested a folder that had none either.
- **git's own refusals are never reimplemented or bypassed** — `worktree remove`
  without `--force` and `branch -d` are the safety net lane inherits by shelling
  out; `--force`/`-D` are used only where the user has just been asked.
- **Every question comes before the first irreversible step** — that is what makes
  abandoning a clean no-op and rollback logic unnecessary.
- **Branch deletion on close applies only to the lane's own branch in branch
  mode** — a detached lane has no branch to delete, and never the base branch.
- **Closing a lane deletes its local branch** — leaving it behind is how a
  repository fills with dead branches, one per lane ever closed. The summary states
  it before the user confirms. Where the work demonstrably landed (git's ancestry
  check, or a `MERGED` pull request) it goes without a second question — including
  the squash case, where `git branch -d` refuses and forcing is correct rather than
  dangerous. Where there is no such evidence, permission is asked, and declining
  keeps the branch and prints the command to remove it later.

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

**Convenience state** — anything lane remembers for convenience rather than
configuration (the last project used, for instance) lives in
`${XDG_STATE_HOME:-~/.local/state}/lane/state.toml`, mode 0600, **never** in the
config file. Adding to that file is not a new configuration key and does not need
asking; it is also disposable, so lane must behave correctly when it is missing or
corrupt. **Adding a new _configuration_ key does need asking.**

**Opening a lane** — pick a project from `<projects_root>/<project>/.git`, take a
one-line task description, derive the lane name from it, fetch origin, resolve the
default branch, then ask for the mode. Branch mode offers `feature/`, `bugfix/`,
`hotfix/`, `chore/`, `refactor/`, `docs/`, the bare lane name, and a free-text
option. Detached mode sits at `origin/<default>` with no branch. Lane metadata —
description, base branch, created timestamp, repo path — lives **outside the
worktree** so it cannot dirty it (`<lanes_root>/<project>/.lane/<lane>`). Then
launch the editor.

**Listing lanes** — for each lane: uncommitted count, unpushed count, merged flag,
detachment, pull request state and age, on a row you can put a cursor on. The
branch is shown too, but in the panel for the row under the cursor rather than in a
column: it is the lane name with a prefix in front of it, and spending forty
columns on it was what left `state` and `pr` — the two that answer *can I close
this* — as the narrowest things on the line. See *The lanes screen* above.

**Closing a lane** — fetch, then three checks: uncommitted or untracked files,
unpushed commits, and whether the work reached `origin/<default>` (including the
pull request check). Everything the close needs to know is asked **before anything
is removed, in one pass**: outstanding findings are listed and confirmed; a lane on
a detached HEAD with unpushed commits is offered a `wip/<lane>` branch; and if the
lane's branch is not merged, permission to force-delete it is asked for here
rather than after the worktree is gone. Only then does it execute: park the rescue
branch if asked, remove the worktree, prune, delete the branch. **Every one of
those steps shows a spinner** — they run after the last question, with nothing on
screen to explain the wait, and removing a worktree of a few thousand files is the
longest thing a close does. **The whole phase defers Ctrl-C**, which is Zone 2 of
*Ctrl-C is answered everywhere* above.

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

### The two structural rules that erode first

1. **Actions ask through the prompt interface; they never import a prompt
   library.** The moment an action imports `prompt_toolkit`, it stops being
   testable without a terminal.
2. **Everything touching git or GitHub sits behind its interface.** No `subprocess`
   call to `git` or `gh` outside the backend/client implementations.

### Standards

**Python 3.14** (`requires-python = ">=3.14"`, ruff `target-version = "py314"`,
mypy `python_version = "3.14"`), `uv` for dependencies and the virtualenv,
`pyproject.toml`, `src/lane/` layout. stdlib `argparse` for the two flags — **do
not** pull in Typer or Click to parse `--version` and `--help`. Prompt and
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
- every step of a close's removal phase announcing itself, in order, after the last
  question
- Ctrl-C during that phase finishing it rather than stopping half-way — a real
  `SIGINT` to the test process, because that is what a terminal sends — and being
  raised afterwards rather than discarded
- Ctrl-C during a spinner abandoning, Ctrl-C inside an action being reported with
  what might be half-done, and the boundary exiting `130` rather than tracing back
- git running outside lane's process group, so the terminal's Ctrl-C cannot reach it
- a non-TTY invocation refusing cleanly while `--version` still works
- the version reaching the build from the tag, and the config stamp being the
  release rather than the moving version of a development checkout
- at least one test driving the session end to end: menu → open a lane → menu →
  lanes → close it → menu → quit, asserting the resulting git state

## Where things stand

`docs/adr/` holds decisions that needed evidence: `0001-git-backend.md` and
`0002-lane-listing.md`. `docs/CONVENTIONS.md` is the presentation rulebook every
screen is held to — read it before laying out a new one.

**Precedence when sources disagree**: this file wins over your own judgement.
Where it is silent, decide for yourself and say so, and update this file in the
same change if the decision should bind future work too.
