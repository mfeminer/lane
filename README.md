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

  ❯ open        Open a new lane: pick a project, describe the task, start editing
    lanes       Every open lane, where it stands, and what to do with it
    settings    Configure lane
    doctor      Check git, gh, the editor and your paths
    quit        Leave lane

  ↑↓ move · enter choose
```

A working day is four steps, and lane is only in two of them:

1. **Run `lane`, choose `open`.** Pick a project, say what you're working on, choose
   a branch. Your editor opens in the new worktree.
2. **Do all the work there.**
3. **Quit the editor.**
4. **Run `lane`, choose `lanes`, put the cursor on the row and press `Enter` →
   `close`.** It checks the pull requests, verifies nothing is left behind, and
   removes the worktree and every branch the lane used.

`↑` `↓` move, `Enter` chooses, `Ctrl-C` backs out — from anywhere, and always safely:
every question comes before the first irreversible step. There are **no subcommands**;
`--version` and `--help` are the only arguments.

## Configure

`~/.config/lane/config.toml`, three settings:

```toml
projects_root = "/Users/you/Projects"   # one git repository per subfolder
lanes_root = "/Users/you/Lanes"         # where lanes are parked
editor = "cursor"                       # code, zed, idea, subl...
```

`LANE_PROJECTS_ROOT`, `LANE_LANES_ROOT` and `LANE_EDITOR` override the file.
Something not working? **doctor** checks every bit of it.

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
