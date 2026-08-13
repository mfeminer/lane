# lane — the long version

Everything the [README](../README.md) leaves out: every screen, every key, what
protects your work when a lane is closed, troubleshooting, and how a release is cut.
The README is the five-minute version; this is the rest of it.

The design decisions *behind* all of this — and the invariants a change must not
regress — live in [AGENTS.md](../AGENTS.md) and [docs/adr/](adr/), not here.

---

## Using it

`lane` takes exactly two arguments:

| | |
|---|---|
| `lane --version` / `-V` | the version and build fingerprint |
| `lane --help` / `-h` | a short summary |

**Everything else is interactive.** Run `lane` with no arguments and you get the
splash — a stretch of road, one task per lane, drawn in `ui/splash.py` — and the menu
under it:

```
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    …the splash, and under it…
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ❯ open        New work, or a branch that already exists — your editor opens in it
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

**One screen adds one key**, and it's the preparation screen below: `Space` ticks the row
under the cursor. That's the universal multi-select keystroke rather than an invention of
this tool, and it's what turns a dozen answers into a dozen keystrokes. On that screen — and
only there — `Enter` accepts everything rather than acting on the row, because the row's
answer is already `Space`'s job. Its footer names both, every time it's up.

**Backing out is always safe.** Every question an action asks comes *before* its
first irreversible step, so leaving half-way through leaves your disk exactly as it
was. There's nothing to undo because nothing has happened yet — which is why lane
doesn't announce anything when you go back; it just shows the menu again.

Leaving closes the road behind you (`see you in the next lane`), whether you chose
`quit` or pressed Ctrl-C at the menu.

lane needs a terminal. Piped or redirected, it says so and exits non-zero —
`--version` and `--help` are the exceptions and work anywhere, including CI.

---

## Opening a lane

lane asks for everything up front, then creates the worktree. After the project it
asks **what the lane is for**, and the two answers lead different ways:

1. **Which project** — the last one you used is offered first.
2. **What is this lane for?**

   - **new work** — you're starting something.
   - **existing branch** — you're picking one up: a colleague pushed it, you
     abandoned it a fortnight ago, or you want to read a pull request locally.

### New work

3. **What you're working on** — one line, in whatever language you think in. The
   lane name is derived from it and is always plain ASCII, capped at 40
   characters: `Login sayfası hatası` → `login-sayfasi-hatasi`.
4. It fetches `origin` and works out the default branch.
5. **How the lane should start:**

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

### An existing branch

lane fetches with `--prune` — so it isn't offering you branches that were deleted on
the remote weeks ago — and then shows you every branch, local and on `origin`, one
row each, **most recently committed first**:

```
  312 branches in Acme.Widgets

  branch                            state                          age
❯ feature/export-csv                                               today
  chore/bump-dependencies           in lane Acme.Widgets/bump-deps  yesterday
  feature/colleague-review          origin only                    2 days ago
  main                              in the main clone              today
  ← Back
```

The `state` column is the one that matters, because **git will not check a branch
out twice**:

| It says | What it means |
|---|---|
| *(nothing)* | yours to take |
| `origin only` | you've never had it locally; lane creates the branch, tracking `origin/<it>` |
| `in the main clone` | your main checkout has it — almost always the default branch |
| `in lane <project>/<lane>` | another lane has it open |
| `in another worktree` | a worktree that isn't lane's has it; the refusal names the path |

Branches you can't take are **shown, not hidden**. A row that isn't there can't tell
you why it isn't there, and the branch you're looking for is very often exactly the
one another lane already has. Choose one and lane refuses with the reason — and for
a branch held by a lane, it offers to **enter that lane instead**, which is usually
what you wanted anyway. Say no and you're back on the list where you left the cursor.

Then lane offers a **lane name**, derived from the branch, for you to edit:

```
Lane name [bugfix-a-long-branch-name-somebody-el]: _
```

It's offered rather than just used because the branch was named by somebody else for
another purpose — so the 40-character cap cuts it somewhere nobody chose — and
because the lane name is a directory you're about to live in. If a lane of that name
is already open, lane says so and asks again. The prefix isn't stripped: it would
save about seven characters and make `feature/x` and `bugfix/x` collide into one
directory.

There's no **detached** here. An existing branch is the opposite of detached.

> **Why can't a lane just check out `main`?** Because your main clone already has it
> checked out, and git refuses to have one branch in two worktrees. Detached mode is
> the closest equivalent: identical content, no branch.

Either way, the worktree then appears at `<lanes root>/<project>/<lane>` and your
editor opens in it.

### What a lane's branch tracks

**A lane's branch never tracks anything but itself.**

A branch lane **creates** is made with `--no-track`, so a bare `git push` inside a
lane **cannot** land on your default branch by accident. The first time you push:

```bash
git push -u origin <branch>
```

lane reminds you of this when it opens the lane.

A branch lane **adopts** from `origin` tracks `origin/<itself>`, which is what you'd
expect and what makes the `↑ N unpushed` count in the listing a real measurement
against a real remote branch. It can't reach your default branch either — it isn't
your default branch. And an adopted branch that was already local keeps whatever
upstream it already had; lane never gives it one it didn't have.

### Where the lane's notes live

The lane's description, base branch, creation time and source repository are kept
*outside* the worktree, in `<lanes root>/<project>/.lane/<lane>`. If they were
inside, they'd show up as an uncommitted change in the very listing that reports
uncommitted changes.

---

## Preparing a lane

A worktree is a fresh checkout, so **everything your `.gitignore` covers isn't in it**.
That's git doing the right thing, and it's also what makes the lane unusable: dependency
trees have to be rebuilt, and an ignored `.env` can't be rebuilt at all.

lane fixes that as part of **entering** a lane — which is why `enter` now means "make the
lane ready, then open the editor", and why opening a lane ends by entering it. It happens
*every* time you go into a lane, not once when it's created, which is what makes an
interrupted or failed preparation fix itself: go in again and it picks up where it stopped.
Nothing anywhere remembers that a lane was left half-ready, because nothing needs to — the
only state is whether the path is there.

### What you're asked, and how often

Once per project, per path. The first time lane sees an ignored path it doesn't have an
answer for, it asks — all of them on one screen, because being asked three questions in a
row on the way to your editor is a toll:

```
Preparing demo/broken-pagination
  Answers are remembered per project — change them in settings · preparation.

  14 paths lane has not been told about

    path                    size      in lane
❯ ✓ node_modules            1.2 GB
  ◐ apps/ · 12 ignored paths  4.2 MB
    console/dist            340 MB    already there

  2 of 14 in · 1.2 GB coming in
  ↑↓ move · space toggle · enter accept · ctrl-c back out
```

**Every row is in or out, and `Space` is what changes it** — under the cursor, in place,
one keystroke, no going into the row and back out again. `Enter` accepts the whole screen
and carries on to your editor. A dozen paths costs a dozen keystrokes and one more.

That's the one place in lane where `Enter` doesn't act on the row you're on, and it's
deliberate: on this screen the row's answer is `Space`'s job, so `Enter` is free to mean
"done" — except on a folder row, which is a screen you can go *into*, and there `Enter`
does exactly what it does everywhere else in lane: it opens the thing under the cursor.
The footer says which of the two you're about to get, every time.

Every row starts **out**, so pressing `Enter` straight away is safe: nothing is copied, and
lane stops asking. Answers are remembered, so the **second** lane in that project asks
nothing at all and just comes up ready.

The line above the footer keeps count — how many are in, and how much is actually about to
be copied. Forty rows don't fit on a screen, and that line is what tells you what you've
decided without scrolling back through them.

The sizes are why the screen is worth reading — they're what stops you bringing in a 20 GB
local database by accident. They're measured while you're already reading the rows, so they
appear a moment after the rest.

### Folders, not two hundred rows

git can only collapse a directory it ignores *entirely*. Put one tracked file in it and
every ignored file inside gets listed separately — a real repository with four ignore
patterns produced **55 rows, 40 of them from a single `logs/`**, and a monorepo with a
`node_modules`, a `dist` and a `.env` under every package reaches a couple of hundred.
Choosing among two hundred flat rows isn't a screen, it's an ordeal.

So the screen shows you the **top** of the tree — where it actually branches — and you go
in from there:

```
    path                        size      in lane
❯ ◐ packages/ · 180 ignored paths  8.4 GB
    node_modules                1.2 GB
    .env                        1.4 KB
```

`Enter` opens `packages/`, and you're on the level below it, with a visible way back:

```
  packages/ · 180 ignored paths

    path                        size      in lane
❯ ✓ packages/api/ · 3 ignored paths  1.1 GB
  ◐ packages/web/ · 3 ignored paths  2.2 GB
    ← Back
```

**One `Space` on a folder answers everything under it**, however deep — all 180 of them
from that first row, if that's what you want. Nobody has to descend into fourteen packages
one at a time. Press it on a folder that's all in and it takes all of it back out.

**`◐` means some in, some out.** A path has two answers and a tick says both; a folder
stands for everything beneath it, so it has three, and a mix gets its own mark rather than
being rounded to one of the others. A `Space` on a mixed folder brings the **whole** thing
in (the press after that takes it all out), so the row's panel tells you how many paths
that is before you press it.

Levels with nothing to choose between don't get a screen of their own:

* a directory holding a single thing is joined onto it — `apps/web/frontend/node_modules`
  stays one row rather than three keystrokes;
* a level that would open on fewer than three rows is drawn where it is instead, since a
  folder has to save more than the one keystroke it costs.

Your place is kept: come back out of a folder and the level above is exactly as you left
it, cursor included.

> **A folder row is never an answer about the folder itself.** That directory is only
> *partly* ignored — that's why its files were listed one by one — so it holds your tracked
> work too. Ticking a folder records one answer per file inside it and never touches the
> directory. Which also means a file that turns up there later is one lane hasn't been told
> about, so it asks, rather than quietly sweeping it in.

### What a tick actually does

A ticked path is copied in from your main clone. On APFS that's a copy-on-write clone: a
64 MB tree takes about a third of a millisecond and no extra disk until something writes to
it. That's what makes this cheap rather than merely automatic. If your projects and lanes
folders are on **different** volumes it can't be a clone at all and becomes a real copy —
slow, and real disk. `doctor` tells you which you've got, and settings warns you when you
tick something and the answer is no.

There's one other kind of step, and it isn't a path: a **command** to run when a lane
opens. A command isn't something lane can discover, so it's added from **settings →
commands** rather than here. It asks for the command, where to run it, and a path that
means "don't bother" (`unless`), so an `install` step runs on a lane that needs it and
skips one that doesn't.

A path your branch actually *tracks* is never offered at all — lane will not write over
your files, and a prepared lane still reads `✓ clean`.

> **There used to be a third answer, `link`** — a symlink into your main clone, always
> current and stored once rather than once per lane. It's gone. A row asks one question with
> two answers, and a checkbox can't carry a third; a screen you had to go *into* to change an
> answer is what this replaced. If lane finds a `link` in an older `prepare.toml` it asks
> about that path again, and the symlink already in your lane simply reads as `already
> there`.

### When a path is already there

The row says so, in its own column, before you answer:

```
    path                       size      in lane
❯ ✓ apps/web/node_modules      1.2 GB    already there
```

**A tick never overwrites what your lane changed.** You may have patched something inside
that tree; ticking the row leaves it exactly as it is, and lane does nothing at all for it.
The column is there so a tick that's a no-op and a tick that copies a gigabyte don't look
the same.

### Changing an answer later

**settings → preparation** opens *the same screen*, over every project at once, with the
project dimmed in front of the path:

```
lane settings · preparation
  /Users/you/.config/lane/prepare.toml

  4 answered paths in 2 projects

    path                              size
❯ ✓ acme-web/apps/web/node_modules    1.2 GB
  ✓ acme-web/apps/web/.env            1.4 KB
    demo/vendor                       84 MB

  2 of 3 in · 1.2 GB in each lane
  ↑↓ move · space toggle · enter accept · ctrl-c back out
```

Same rows, same keystroke, same footer. The running total reads **in each lane** rather
than *coming in*, because accepting here copies nothing — it answers for every lane in
that project from now on. Changing a decision you made months ago is one
`Space` — which is the whole point of it being one screen rather than two that look alike.
There's no `in lane` column here, because there's no lane in hand; nothing is copied when
you accept, and the next lane you enter in that project acts on the answers.

**settings → commands** is the other half: the `run` steps, which are typed rather than
discovered and have a directory and a guard to edit. `Enter` on one offers `change` and
`forget`, and `add a command` is where a new one comes from.

### About secrets

Copying a `.env` into every lane multiplies the number of places that secret lives. Closing
the lane takes it with the worktree — but a close you refused or interrupted doesn't. So the
row says so while you're deciding, and again once you have:

```
! apps/console/.env looks like it holds secrets, and every lane now gets a copy.
  Leave it out in settings · preparation to stop that.
```

It's a suggestion, not a refusal.

### When it goes wrong

A step that fails says so and names what to do; the **other steps still run**, and the
editor **still opens** — a lane that's mostly ready beats one you can't get into.

```
✗ Could not clone apps/web/node_modules: No such file or directory
  The lane still opens; entering it again tries this step once more.
```

`Ctrl-C` during a step stops there and tells you where it stopped. Nothing is left half
copied: every clone is written beside its target and moved into place in one step, so the
path is either the old one or the new one. Go into the lane again and it finishes the job.

```
! Interrupted while cloning apps/web/node_modules
  Entering the lane again finishes the job.
```

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

If somebody's pull request is **based on** your lane's branch, `state` says `↳ 1
stacked` and the panel names it. It's in `state` rather than `pr` because `pr` is your
own pull requests, and because it changes what closing does — the branch is about to
be deleted and their review is built on it:

```
  lane                state                    pr           age
❯ broken-pagination   ✓ merged · ↳ 1 stacked   #41 merged   today

  bugfix/broken-pagination
  PR #41 merged — https://github.com/you/demo/pull/41 · base of #99
```

Press `Enter` on a row and you get its two verbs:

```
demo/broken-pagination

  ❯ enter    prepare the lane, then open the editor in it
    close    safety checks, then remove the worktree
    ← Back

  ↑↓ move · enter choose
```

Close a lane and you stay right here, one row shorter, so closing three of them
doesn't mean three trips back to the menu. Enter one and lane gets out of the way —
you're in the editor now. If entering has something to ask you first, that's
[preparation](#preparing-a-lane); back out of it and you're right back at this table.

### It doesn't wait for GitHub

Git status is local and quick, so the table is drawn as soon as it's read. Pull
request state is two `gh` calls per lane — what came from this branch, and what's
based on it — which isn't, so the `pr` column starts as `checking…` and fills in while
you're already reading. Status for all lanes is collected in parallel, so this stays
fast when you have a lot of them.

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

### Pull requests built on your branch

Closing deletes the branch, and deleting a base breaks the pull request stacked on it.
Your own work landing doesn't make that safe — your pull request can be merged and your
tree clean, and closing would still take out an open review. So lane asks GitHub the
other question too, what's based on this branch, and blocks:

```
! PR #99 is based on this branch, so deleting it would break that pull request
  — https://github.com/you/demo/pull/99
```

Only *open* ones count: a closed or merged pull request based on your branch isn't at
risk from anything the close does. And if that question can't be answered, the close is
refused just as it is for your own pull request — "nobody could be reached to ask"
isn't permission to delete somebody's base.

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

**A branch your lane adopted rather than created is treated the same way**, and
that's deliberate: only the *local* branch is deleted and the one on `origin` is
never touched, so a branch you picked up from the remote is a `git fetch` away from
being back. Where nothing demonstrably landed — a purely local branch you took over,
say — you get the same question above before anything goes.

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

It also answers the one question about [preparation](#preparing-a-lane) you can't see for
yourself — whether bringing a path in can actually be a copy-on-write clone:

```
! Copy-on-write is not available: /Users/you/Projects and /Volumes/Work/Lanes are on
  different volumes, so bringing a path in is a real copy — slow, and it uses real disk.
  Put both roots on one volume, or leave the large paths out.
```

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

### The preparation answers

`~/.config/lane/prepare.toml`, same modes, **a separate file on purpose**: it's an
unbounded list rather than three settings, and lane rewrites `config.toml` whenever the
version stamp changes, carrying over the keys it knows about — which this isn't one of.

```toml
version = "0.0.3"          # managed by lane

[[step]]
project = "acme-web"
path = "apps/web/node_modules"
verb = "clone"

[[step]]
project = "acme-web"
verb = "run"
command = "yarn install"
directory = "apps/web"
unless = "apps/web/node_modules"
```

Projects are named, not pathed, so moving your whole projects folder keeps every answer;
*renaming a project* means lane asks about it again, exactly as that project also gets a
fresh lanes folder. Delete the file and you've reset every answer without touching your
three settings. If it's unreadable lane says so and simply asks again — nothing else
breaks.

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

**lane keeps asking me about the same path** — you answered it for a *different* project
name, or the project directory was renamed. Answers are keyed by project name; check
**settings → preparation**.

**A path I ticked isn't in my lane** — it has to exist in your main clone for there to be
anything to copy, and it has to be ignored by the lane's own `.gitignore`. A lane branched
from an older base that predates the `.gitignore` entry ignores nothing, so nothing is
offered. And if the path was **already there**, ticking it does nothing on purpose: lane
never overwrites what your lane changed.

**Bringing paths in is slow and eating disk** — your projects and lanes folders are on
different volumes, so it can't be a copy-on-write clone. `doctor` says so explicitly; leave
the big paths out and use a `run` command instead, or put both folders on one volume.

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

Before changing anything, read **[AGENTS.md](../AGENTS.md)**: it holds the design
decisions, the four seams, and the invariants that must not regress, each with its
reason. **[docs/adr/](adr/)** holds the decisions that needed evidence — in
particular [why lane drives the `git` CLI](adr/0001-git-backend.md) instead of
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

**If you publish a release from GitHub's web UI instead**, that creates the tag too, so
CD still runs — it finds the release already there and attaches the binary to it,
leaving your title and notes as you wrote them. Either door ends with the binary on the
release, which is what the install instructions depend on. The tag command is still the
one to prefer: it makes an annotated tag, where the UI makes a lightweight one.

**The notes are generated from the pull requests** merged since the previous tag,
grouped by the labels in [`.github/release.yml`](../.github/release.yml) —
`enhancement` under *Added*, `bug` under *Fixed*, and `documentation` /
`dependencies` left out. An unlabelled pull request still shows up, under *Other
changes*, so a forgotten label costs you the grouping and not the entry.

**Between tags**, `lane --version` reads `0.0.2.post1.dev4+g1a2b3c4` — "after
0.0.2, unreleased". The config file records the release it came from (`0.0.2`)
rather than the full build string, which would otherwise move with every commit
and rewrite `config.toml` on every run.

---

