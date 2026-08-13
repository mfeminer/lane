# lane

> Built with Claude in nearly YOLO mode. Almost nothing here was coded or changed
> by hand.

Run several pieces of work side by side, each in its own git worktree.

A **lane** is one task: its own working copy, its own branch, its own editor window.
No stashing, no `git checkout` between half-finished jobs. lane creates the worktree
and the branch when you start, and clears both away once the work has landed.

---

## Install

macOS on Apple silicon, with `git`, [`gh`](https://cli.github.com) (logged in) and an
editor command on your PATH — `cursor`, `code`, `zed`, `idea`, `subl`.

```bash
mkdir -p ~/bin
curl -fsSL -o ~/bin/lane https://github.com/mfeminer/lane/releases/latest/download/lane-macos-arm64
chmod +x ~/bin/lane
xattr -d com.apple.quarantine ~/bin/lane   # it is not notarised
```

Then run `lane`, choose **settings**, and answer three questions: where your projects
sit, where lanes should be parked, and which editor to open.

## Use it

```
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ╭─────╮
  │ one │
  ╰─○─○─╯
  ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌
                   ╭──────╮
                   │ task │
                   ╰─○──○─╯
  ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌
                                    ╭─────╮
                                    │ per │
                                    ╰─○─○─╯
  ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌ ╌
                  ┏━━━━━━━━━━━━━━━━━━━━━━━━━┓
                  ┃ █     ▄▀▀▄  █▄  █  █▀▀▀ ┃
                  ┃ █     █▄▄█  █ ▀▄█  █▀▀  ┃
                  ┃ █▄▄▄  █  █  █   █  █▄▄▄ ┃
                  ┗━━━○━━━━━━━━━━━━━━━━━○━━━┛           v0.0.2
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ❯ open        New work, or a branch that already exists — your editor opens in it
    lanes       Every open lane, where it stands, and what to do with it
    settings    Configure lane
    doctor      Check git, gh, the editor and your paths
    quit        Leave lane

  ↑↓ move · enter choose
```

A working day is four steps, and lane is only in two of them:

1. **Run `lane`, choose `open`.** Pick a project, then say whether this is new work
   or a branch that already exists — a colleague's, or one you left a fortnight ago.
   New work asks what you're working on and what to call the branch; an existing
   branch is picked from a list and names the lane itself. Either way your editor
   opens in the new worktree.
2. **Do all the work there.**
3. **Quit the editor.**
4. **Run `lane`, choose `lanes`, put the cursor on the row and press `Enter` →
   `close`.** It checks the pull requests, verifies nothing is left behind, and
   removes the worktree and every branch the lane used.

A new worktree is a fresh checkout, so everything your `.gitignore` covers is missing from
it — `node_modules`, build caches, your `.env`. The first time lane sees one of those it
asks, once per project, what to do with it:

```
Preparing demo/broken-pagination
  Answers are remembered per project — change them in settings · preparation.

  14 paths lane has not been told about

    path                          size      in lane
❯ ✓ apps/web/node_modules         1.2 GB
  ✓ apps/web/ · 12 ignored files  4.2 MB
    apps/console/dist             340 MB    already there

  2 of 3 in · 1.2 GB coming in
  ↑↓ move · space toggle · enter accept · ctrl-c back out
```

`Space` ticks the row under the cursor; `Enter` accepts the whole screen. A dozen paths is
a dozen keystrokes and one more — no going into a row and back out again. Ticked means the
path is copied in from your main clone, which on APFS is copy-on-write and costs almost
nothing and almost no disk. Answer once and every lane in that project after it comes up
ready.

A path that is **already there** is left exactly as it is: ticking it never overwrites
something you changed inside the lane.

Loose ignored files are folded into one row per folder — git only collapses a directory it
ignores *entirely*, so one tracked file in it and you'd otherwise get a row per file. One
`Space` answers the whole folder. If you've already answered its files differently, the
folder is opened out into its own rows instead, so the tick never says something untrue.

`↑` `↓` move and `Ctrl-C` backs out, from anywhere, and always safely: every question comes
before the first irreversible step. There are **no subcommands**; `--version` and `--help`
are the only arguments.

## Configure

`~/.config/lane/config.toml`, three settings:

```toml
projects_root = "/Users/you/Projects"   # one git repository per subfolder
lanes_root = "/Users/you/Lanes"         # where lanes are parked
editor = "cursor"                       # code, zed, idea, subl...
```

`LANE_PROJECTS_ROOT`, `LANE_LANES_ROOT` and `LANE_EDITOR` override the file. What to do
with each project's ignored paths lives beside it in `prepare.toml`. **settings →
preparation** opens the very screen above, over every project at once, so changing an
answer is the same one keystroke wherever you came from; **settings → commands** is where
you add a command to run when a lane opens. Something not working? **doctor** checks every
bit of it — including whether your projects and lanes folders can actually share blocks,
which is what makes bringing a path in free.

## Develop

```bash
uv sync && make check     # lint, types, tests
make build                # PyInstaller one-file -> dist/lane
```

Read **[AGENTS.md](AGENTS.md)** before changing anything: it holds the design
decisions and the invariants that must not regress.

---

**The long version:** [docs/GUIDE.md](docs/GUIDE.md) — every screen, every key, what
protects your work when a lane is closed, troubleshooting, and how a release is cut.

[MIT](LICENSE).
