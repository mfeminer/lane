# lane

Run several pieces of work side by side, each in its own git worktree.

A **lane** is one task: its own working copy, its own branch, its own editor
window. You open a lane when you start something and close it when it has landed.

No stashing. No `git checkout` between half-finished jobs. No "let me just commit
this WIP so I can look at that bug". Each task gets its own directory and its own
branch, and lane looks after creating them and cleaning them up.

---

## The working day

This is the whole workflow. There are four steps and lane is only involved in two.

1. **Run `lane`, open a lane.** Pick a project, say what you're working on, choose
   a branch. Your editor opens in the new worktree.
2. **Do all the work there.** The editor's integrated terminal is already inside
   the worktree, so everything — tests, builds, git — just works.
3. **Quit the editor.**
4. **Run `lane` again, open `lanes`, and close it.** Put the cursor on the lane and
   press `Enter`. It checks the pull request, verifies nothing is left behind, and
   removes the worktree.

lane is touched at the two ends only. It is deliberately **not** part of your
edit-test loop.

---

## Installing

### 1. Prerequisites

| | Why |
|---|---|
| **macOS on Apple silicon** | what the prebuilt binary targets today |
| **`git`** on your PATH | lane drives the `git` command line |
| **[`gh`](https://cli.github.com)**, logged in | to check pull requests when closing a lane |
| **An editor with a shell command** | `cursor`, `code`, `zed`, `idea`, `subl` |

```bash
brew install gh
gh auth login
```

`git` is checked once when lane starts. `gh` is only needed to close a lane that
has a GitHub remote and a branch — everything else works without it, and lane
tells you exactly which command to run if it ever matters.

If the `cursor` command is missing: open Cursor → `Cmd+Shift+P` →
*Shell Command: Install 'cursor' command*. lane also spots Cursor, VS Code and Zed
installed as `.app`s without their shell command, and uses `open -a` instead.

**You do not need `fzf`** — the picker is built in. **You do not need Python** —
the binary is self-contained.

### 2. Install

Download the binary from the [latest
release](https://github.com/mfeminer/lane/releases/latest):

```bash
mkdir -p ~/bin
curl -fsSL -o ~/bin/lane https://github.com/mfeminer/lane/releases/latest/download/lane-macos-arm64
chmod +x ~/bin/lane
xattr -d com.apple.quarantine ~/bin/lane   # it is not notarised
```

Or build it yourself from a checkout:

```bash
make build
mkdir -p ~/bin && cp dist/lane ~/bin/lane
```

If `~/bin` isn't on your PATH yet:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

### 3. Check you're running the copy you just installed

```bash
lane --version
```

```
lane 0.0.2 (build accc87d)
```

The build is a fingerprint of the binary itself, so two copies with the same
version number still report different builds. If the build doesn't match what you
just installed, an older `lane` is earlier on your PATH — `which -a lane` will show
you. `doctor` reports the same thing plus the full path of what's running.

### 4. First run

Run `lane`, choose **settings**, and answer three questions:

- **Which folder do your projects sit in?** One git repository per subfolder:
  `<folder>/<project>/.git`. The folder itself is not a repository.
- **Where should lanes be parked?** lane offers a folder beside your projects one
  (`/x/y/projects` → `/x/y/Lanes`); change it to anywhere outside the projects
  folder if you prefer.
- **Which editor command?** `cursor`, `code`, `zed`, …

That's it. Choose **open** and you have your first lane.

---

## Using it

`lane` takes exactly two arguments:

| | |
|---|---|
| `lane --version` / `-V` | the version and build fingerprint |
| `lane --help` / `-h` | a short summary |

**Everything else is interactive.** Run `lane` with no arguments and you get a
menu:

```
lane 0.0.2

  ❯ open        Open a new lane: pick a project, describe the task, start editing
    lanes       Every open lane, where it stands, and what to do with it
    settings    Configure lane
    doctor      Check git, gh, the editor and your paths
    quit        Leave lane

  ↑↓ move · enter choose
```

There's no `enter` or `close` here: **`lanes` is where you do both.** They used to be
their own entries, and each of them started by asking you to pick a lane from a list
that showed you the names and nothing else — while the listing right next door showed
you the names *and* what state each one was in. Now you look and act in one place.

Pick an action and lane walks you through it. Most drop you back at the menu when
they're done; `lanes` keeps you until you leave it, because closing three lanes
shouldn't mean three trips through here.

> **There are no subcommands.** `lane open` is an error, not a shortcut. The menu is
> the only way in, which means there's only one list of things lane can do and it
> can't fall out of step with itself.

### Keys

There is almost nothing to learn, because **going back is something you can see**:
every list ends with a `← Back` entry, the lanes table ends with a `← Back to the
menu` row, and the main menu ends with `quit`.

| Key | What it does |
|---|---|
| `↑` `↓` | move through a list or a table (`Home` / `End` jump to the ends) |
| `Enter` | choose, or accept what you typed |
| `y` / `n` | answer a yes/no question; `Enter` takes the default shown in `[y/N]` |
| `Ctrl-C` | back out, from anywhere |

That's the whole list. No `q`, no vim keys, no number shortcuts — and `Esc` is not
bound to anything, so you never need it. In a text prompt you also get the line
editing you'd expect: **Option+←/→ to move by word**, Option+Backspace to delete
one, Ctrl-A and Ctrl-E for the ends.

The lanes table didn't add a key either — there's no `c` for close. That's why
`Enter` on a row offers you its verbs instead of a legend telling you which letters
do what.

**Backing out is always safe.** Every question an action asks comes *before* its
first irreversible step, so leaving half-way through leaves your disk exactly as it
was. There's nothing to undo because nothing has happened yet — which is why lane
doesn't announce anything when you go back; it just shows the menu again.

lane needs a terminal. Piped or redirected, it says so and exits non-zero —
`--version` and `--help` are the exceptions and work anywhere, including CI.

---

## Opening a lane

lane asks for everything up front, then creates the worktree:

1. **Which project** — the last one you used is offered first.
2. **What you're working on** — one line, in whatever language you think in. The
   lane name is derived from it and is always plain ASCII, capped at 40
   characters: `Login sayfası hatası` → `login-sayfasi-hatasi`.
3. It fetches `origin` and works out the default branch.
4. **How the lane should start:**

   - **branch** — pick the name right there. You get `feature/`, `bugfix/`,
     `hotfix/`, `chore/`, `refactor/`, `docs/`, the bare lane name, or *other…* to
     type your own. Hand-typed names are cleaned up (`EMİN/deneme  şube!!` →
     `EMIN/deneme-sube`) and validated with `git check-ref-format`; if git rejects
     it, lane asks again rather than giving up.
   - **detached** — sits at `origin/<default branch>` with no branch. Create one
     yourself whenever you're ready.

   Branch naming is **per lane, on purpose**. It describes the task, not your
   machine, so this lane can be `bugfix/…` while the next is `feature/…`. There's no
   global setting for it.

> **Why can't a lane just check out `main`?** Because your main clone already has it
> checked out, and git refuses to have one branch in two worktrees. Detached mode is
> the closest equivalent: identical content, no branch.

Then the worktree appears at `<lanes root>/<project>/<lane>` and your editor opens
in it.

### New branches have no upstream, deliberately

A lane's branch is created with `--no-track`. That means a bare `git push` inside a
lane **cannot** land on your default branch by accident. The first time you push:

```bash
git push -u origin <branch>
```

lane reminds you of this when it opens the lane.

### Where the lane's notes live

The lane's description, base branch, creation time and source repository are kept
*outside* the worktree, in `<lanes root>/<project>/.lane/<lane>`. If they were
inside, they'd show up as an uncommitted change in the very listing that reports
uncommitted changes.

---

## Your lanes

`lanes` is one screen. Arrow keys move a cursor over the rows, and whatever you do
next happens to the row you're on.

```
  3 open lanes in demo

  lane                state                            pr           age
❯ broken-pagination   ● 1 uncommitted · ↑ 2 unpushed    #41 open     today
  audit-log           ✓ merged                         #38 merged   3 days ago
  just-started        no commits yet                   none         today
  ← Back to the menu

  bugfix/broken-pagination
  PR #41 open — https://github.com/you/demo/pull/41

  ↑↓ move · enter choose
```

The screen is built around one question: **which of these can I close, and what's
stopping the rest?** That's why `state` and `pr` get the room. The lines under the
table describe the row your cursor is on — the branch, the pull request, and the
task description when the lane name couldn't keep all of it.

`✓ merged` is only shown when the lane's own commits actually reached the base
branch. A lane you opened a minute ago says **no commits yet** — it sits exactly at
the base branch, so a plain ancestry check would call it "merged" when there has
never been anything to merge.

When a branch has had several pull requests, `pr` shows the one that decides and the
panel keeps the rest, so nothing is lost off the row:

```
  bugfix/broken-pagination
  PR #42 open — https://github.com/you/demo/pull/42 · earlier: #41 merged
```

Press `Enter` on a row and you get its two verbs:

```
demo/broken-pagination

  ❯ enter    relaunch the editor in this lane
    close    safety checks, then remove the worktree
    ← Back

  ↑↓ move · enter choose
```

Close a lane and you stay right here, one row shorter, so closing three of them
doesn't mean three trips back to the menu. Enter one and lane gets out of the way —
you're in the editor now.

### It doesn't wait for GitHub

Git status is local and quick, so the table is drawn as soon as it's read. Pull
request state is a `gh` call per lane, which isn't, so the `pr` column starts as
`checking…` and fills in while you're already reading. Status for all lanes is
collected in parallel, so this stays fast when you have a lot of them.

If `gh` can't be asked at all, the column says `unknown` — which is a different
thing from `none`, and the panel tells you which command fixes it:

```
  Pull request state unknown — gh is not installed. Fix with: brew install gh
```

The listing never refuses to render.

---

## Closing a lane

You close a lane from `lanes`, with the cursor on it. lane fetches `origin`, then
runs three checks:

1. **Uncommitted or untracked files**
2. **Unpushed commits**
3. **Whether the work reached `origin/<default branch>`**

It shows you everything it found, spells out exactly what's about to be removed,
and asks for every decision it needs — *including* permission to force-delete an
unmerged branch — **before touching anything**.

```
Closing demo/broken-pagination
  Broken pagination

✓ Working tree is clean.
✓ Nothing left to push.
✓ PR #41 is merged (squashed or rebased, which is why git's ancestry check
  disagrees) — https://github.com/acme/demo/pull/41

About to remove
  Worktree : /Users/you/Lanes/demo/broken-pagination
  Branch   : bugfix/broken-pagination

✓ Lane is clear.
  Close it? [y/N]
```

Back out at any point and nothing changes.

### The pull request check

Git's ancestry check gives a **false negative** when a pull request is squashed or
rebased on merge: your commits never literally appear in the default branch, so git
says "not merged" about work that shipped last week. lane asks GitHub instead.

| PR state | Verdict |
|---|---|
| `MERGED` | **clean** — even when git's own check disagrees |
| `OPEN` | blocking, reported with its URL |
| `CLOSED` | blocking, reported with its URL |
| none found | blocking |

A branch can have had **more than one** pull request — one merged, a follow-up open —
and lane tracks all of them. The one that decides is the open one if there is one,
whatever its age, otherwise the newest merged; the rest are reported alongside it. So
an earlier merge doesn't make a lane closeable while a follow-up is still open: that
work hasn't landed, and closing the lane would take the branch it's on.

A merged pull request also isn't a blanket pass for everything on the branch. What it
carried is safe; anything you committed **after** it merged exists in that worktree and
nowhere else, so lane counts those separately and still blocks:

```
! 2 commit(s) made after PR #41 merged, and never pushed
```

If you amended or rebased the branch after it merged, the commit that landed is gone
from it and lane can't tell the two apart — so it says so and refuses, rather than
guessing in a direction that could lose the commits.

Lanes on a **detached HEAD** and lanes whose `origin` **isn't GitHub** skip this
entirely — there's no pull request to ask about, so those closes go on git's own
evidence and never invoke `gh`.

If a GitHub-backed lane *can't* be checked because `gh` is missing or logged out,
lane **refuses that close** and tells you which command to run. It won't guess.

### The local branches go with the lane

Closing a lane deletes its local branch too — otherwise your repository fills up
with dead branches, one per lane you ever closed. The summary says so before you
confirm:

```
About to remove
  Worktree : /Users/you/Lanes/demo/broken-pagination
  Branch   : bugfix/broken-pagination — will be deleted
```

**Every** branch the lane used, not just the one you're standing on. Switch branches
mid-task — a fix-up, a second attempt, a rename — and they're all part of the lane, so
they all go:

```
About to remove
  Worktree : /Users/you/Lanes/demo/broken-pagination
  Branch   : bugfix/broken-pagination-v2 — will be deleted
  Branch   : bugfix/broken-pagination — will be deleted (this lane used it earlier)
```

lane finds them from the worktree's own history, so you don't have to remember. Any
that still hold unique work are marked, and one question covers them.

When the work demonstrably landed — git says so, or the pull request is `MERGED` —
the branch is deleted without a second question. That includes the squash-merge
case, where `git branch -d` refuses because the commits exist nowhere in the base;
lane has the pull request as evidence, so it deletes anyway.

When there's **no** evidence it landed, deleting could lose work, so lane asks:

```
!   Branch   : feature/risky — will be deleted, and it is not merged
    Branch 'feature/risky' is not merged. Delete it anyway? [y/N]
```

Decline and the branch is kept, with the exact command to remove it later.

### What protects your work

- A lane on a **detached HEAD with unpushed commits** is offered a `wip/<lane>`
  branch before removal, so nothing becomes unreachable. That branch is never
  deleted afterwards — that would defeat the point.
- **Every question comes before anything is removed**, so declining leaves
  everything as it was.
- Only the lane's **own** branch is ever deleted, and only in branch mode — never
  the base branch, never a detached lane (it has none), never a `wip/` branch.
- lane never bypasses git's own refusals. `git worktree remove` won't discard a
  dirty tree and `git branch -d` won't drop an unmerged branch — lane inherits both
  and only overrides them at a point where you've just said yes.

---

## Diagnostics

**doctor** reports every prerequisite, your paths, how many projects and open lanes
it can see, and which copy of lane is running. It works on a machine where *none*
of what it inspects is installed — it's the action that explains a missing
prerequisite, so it's never hidden behind one.

If no projects turn up, lane says how many subfolders it looked at, and if your
repositories are nested one level too deep (`<root>/<org>/<repo>`) it points at the
folder you should use instead.

---

## Configuration

`~/.config/lane/config.toml` (XDG — honours `XDG_CONFIG_HOME`), mode `0600` in a
`0700` directory.

```toml
version = "0.0.2"                       # managed by lane, don't edit

projects_root = "/Users/you/Projects"   # where your repos live
lanes_root = "/Users/you/Lanes"         # where lanes are parked
editor = "cursor"                       # code, zed, idea, subl...
```

Three settings, and `projects_root` is the important one: the folder your projects
**sit in**, one repository per subfolder. Settings won't accept a folder that
contains no repositories, because everything else depends on it being right.

### Environment overrides

`LANE_PROJECTS_ROOT`, `LANE_LANES_ROOT` and `LANE_EDITOR` override the file. When
one is active, settings still edits the file but says plainly that the environment
is currently winning — otherwise saving a value that then appears not to work looks
like a bug.

### Upgrading

Copy the new binary over the old one. If the config on disk was written by a
different version, lane rewrites it in place, carries your values over, keeps a
`.bak`, and says so in one short line. What actually changed is on the [releases
page](https://github.com/mfeminer/lane/releases) — the upgrade notice deliberately
stays a single line.

A config in the old shell-sourced format (`LANE_PROJECTS_ROOT="..."`) is migrated
to TOML automatically on first run.

### State

Things lane remembers for convenience — the last project you used — live in
`~/.local/state/lane/state.toml`, separate from your configuration. That file is
disposable: delete it and lane carries on.

---

## Troubleshooting

**"lane is interactive and needs a terminal"** — you piped or redirected it. Only
`--version` and `--help` work that way.

**"does not understand open"** — there are no subcommands. Run `lane` and pick from
the menu.

**`--version` shows a build I don't recognise** — an older copy is earlier on your
PATH. Check with `which -a lane`.

**"Cannot verify the pull request"** — run `brew install gh` or `gh auth login`, as
the message says. Or close a lane whose remote isn't GitHub, which never needs `gh`.

**"Could not determine the default branch"** — lane won't guess, because basing a
lane on the wrong branch silently is worse than stopping. Fix it with:

```bash
git remote set-head origin --auto
```

**No projects found** — `projects_root` should be the folder *containing* your
repositories, not a repository itself and not its parent. doctor will tell you
which way it's wrong.

**My editor didn't open** — the lane was still created; check `doctor` for whether
your editor command is on PATH. lane prints the path so you can open it yourself.

---

## Development

### Requirements

- **Python 3.14** and [`uv`](https://docs.astral.sh/uv/) — `uv` will fetch the
  interpreter if you don't have it. Users of the built binary need no Python at
  all.
- **macOS on Apple silicon** to produce a working `dist/lane` — that's the only
  target `make build` and CI/CD build for today.
- `git` on PATH. The test suite runs against real temporary repositories, so it
  also needs a `git config user.email`/`user.name` set (locally or via CI).

### Building

```bash
uv sync            # dependencies and virtualenv
make test          # pytest
make lint          # ruff check + format check
make types         # mypy --strict
make check         # all three
make build         # PyInstaller one-file -> dist/lane
```

The suite runs against **real temporary git repositories** — a bare "remote" plus a
clone — so worktree creation, fetching and merge detection are exercised for real.
It never authenticates to GitHub, reaches the network, or opens an editor.

Before changing anything, read **[AGENTS.md](AGENTS.md)**: it holds the design
decisions, the four seams, and the invariants that must not regress, each with its
reason. **[docs/adr/](docs/adr/)** holds the decisions that needed evidence — in
particular [why lane drives the `git` CLI](docs/adr/0001-git-backend.md) instead of
linking a git library.

Two rules erode first, so they're worth stating here too:

1. **Actions ask through the `Ui` interface** — they never import
   `prompt_toolkit` or `rich`. The moment one does, it stops being testable
   without a terminal.
2. **Everything touching git or GitHub sits behind its interface** — no
   `subprocess` call to `git` or `gh` outside `git/cli_backend.py` and
   `github/gh_client.py`.

### CI/CD

- **CI** (`.github/workflows/ci.yml`) runs on every push and pull request:
  lint, types, tests, then `make build` and a smoke test of the binary — for
  verification only. It never publishes anything.
- **CD** (`.github/workflows/cd.yml`) runs only on a pushed tag matching `v*`:
  it builds the binary and publishes a GitHub release with the binary attached.
  It does not run the test suite — CI already gates every push.

### Releasing a new version

**The tag is the version, and tagging is the whole release.** It's derived from
`git describe` by `hatch-vcs`, and no file in the repository carries the number —
so nothing can disagree with the tag. There is no `__version__` to bump and no
changelog to write.

```bash
git tag -a v0.0.3 -m "..." && git push --tags
```

CD builds the binary, refuses to publish if its `--version` doesn't match the tag,
and otherwise publishes a GitHub release with `lane-macos-arm64` attached.

**The notes are generated from the pull requests** merged since the previous tag,
grouped by the labels in [`.github/release.yml`](.github/release.yml) —
`enhancement` under *Added*, `bug` under *Fixed*, and `documentation` /
`dependencies` left out. An unlabelled pull request still shows up, under *Other
changes*, so a forgotten label costs you the grouping and not the entry.

**Between tags**, `lane --version` reads `0.0.2.post1.dev4+g1a2b3c4` — "after
0.0.2, unreleased". The config file records the release it came from (`0.0.2`)
rather than the full build string, which would otherwise move with every commit
and rewrite `config.toml` on every run.

---

## License

[MIT](LICENSE).
