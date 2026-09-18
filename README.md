# lane

> Built with Claude in nearly YOLO mode. Almost nothing here was coded or changed
> by hand.

Run several pieces of work side by side, each in its own git worktree.

A **lane** is one task: its own working copy, its own branch, its own editor window.
No stashing, no `git checkout` between half-finished jobs. lane creates the worktree
and the branch when you start, and clears both away once the work has landed.

---

## Install

macOS on Apple silicon, or Windows on x86-64. Either way you need `git`,
[`gh`](https://cli.github.com) (logged in) and an editor command on your PATH —
`cursor`, `code`, `zed`, `idea`, `subl`.

### macOS

```bash
brew install mfeminer/tap/lane
```

The full name is needed the first time: Homebrew will not load a formula from a tap you
have not trusted, and `brew tap` on its own does not grant that — naming the formula in
full does, with no prompt to answer. After that the short name works for everything, and
**`brew upgrade lane` is how it updates from here on** — which the manual install below
never had an answer for beyond running the same `curl` again and hoping you remembered
to. The formula lives in [mfeminer/homebrew-tap](https://github.com/mfeminer/homebrew-tap).

**Without Homebrew**, the binary is on the release and needs three things doing to it by
hand — fetching, marking executable, and clearing the quarantine flag macOS puts on a
download, because lane is not notarised:

```bash
mkdir -p ~/bin
curl -fsSL -o ~/bin/lane https://github.com/mfeminer/lane/releases/latest/download/lane-macos-arm64
chmod +x ~/bin/lane
xattr -d com.apple.quarantine ~/bin/lane   # it is not notarised
```

If you installed that way before and have since moved to Homebrew, delete `~/bin/lane`:
whichever comes first on your `PATH` wins, and an old copy left there will quietly keep
running instead of the one `brew upgrade` maintains.

### Windows

```powershell
scoop bucket add mfeminer https://github.com/mfeminer/scoop-bucket
scoop install mfeminer/lane
```

The bucket has to be added first, the same shape as trusting a Homebrew tap: Scoop only
installs from buckets you have named. After that **`scoop update lane` is how it updates
from here on** — which the manual install below never had an answer for beyond fetching
the same file again and hoping you remembered to. The manifest lives in
[mfeminer/scoop-bucket](https://github.com/mfeminer/scoop-bucket), and it pins each
release's `sha256`, so Scoop verifies what it downloaded before putting it on your
`PATH`.

Scoop is not on a Windows machine by default; if you have not got it,
[scoop.sh](https://scoop.sh) is one line of PowerShell.

**Without Scoop**, the binary is on the release. Download
[`lane-windows-x86_64.exe`](https://github.com/mfeminer/lane/releases/latest/download/lane-windows-x86_64.exe),
rename it to `lane.exe`, and put it in a folder that is on your `PATH`.

**A copy downloaded that way will probably show "Windows protected your PC" the first
time.** lane is not code-signed, so SmartScreen holds a file your browser marked as
coming from the internet — the same honesty as the macOS quarantine note above, and the
same answer: **More info → Run anyway**. It is asked once per downloaded copy.

### Then

Run `lane`, choose **config**, and answer three questions: where your projects sit,
where lanes should be parked, and which editor to open.

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
    list        Every open lane, where it stands, and what to do with it
    config      Configure lane
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
4. **Run `lane`, choose `list`, put the cursor on the row and press `Enter` →
   `close`.** It checks the pull requests, verifies nothing is left behind, and
   removes the worktree and every branch the lane used.

A new worktree is a fresh checkout, so everything your `.gitignore` covers is missing from
it — `node_modules`, build caches, your `.env`. The first time lane sees one of those it
asks, once per project, what to do with it:

```
Preparing demo/broken-pagination
  Answers are remembered per project — change them in config · preparation.

  14 paths lane has not been told about

    path                        size      in lane
❯ ✓ node_modules               1.2 GB
  ? apps/ · 12 ignored paths   4.2 MB
  ✗ vendor                     88 MB
  ○ console/dist               340 MB    already there

  1 of 14 in · 1.2 GB coming in
  ↑↓ move · space answer
```

`Space` answers the row under the cursor; a dozen paths is a dozen keystrokes, with no
going into a row and back out again. `✓` means the path is copied in from your main clone
— on macOS, where both folders share an APFS volume, that is a copy-on-write clone and
costs almost nothing and almost no disk; on Windows it is a real copy, and **doctor tells
you which one you are getting**. `✗` means you have decided to leave it out. `○` means you have not said yet — and lane will ask again
next time rather than deciding for you.

Below the paths are two more rows: **`apply`** records everything you have decided and
gets on with it, and **`discard`** records nothing. Both are there on every level of the
screen. Answer once and every lane in that project after it comes up ready.

A path that is **already there** is left exactly as it is: answering it *in* never
overwrites something you changed inside the lane.

A real repository can hide a couple of hundred ignored paths under package after package,
so the screen shows the **top** of the tree rather than every leaf: a row like
`apps/ · 12 ignored paths` is a folder you open with `Enter`, with a `← Back` row inside
it that keeps everything you have answered. One `Space` on it answers everything beneath
it, however deep. On a folder, `?` means there is still an unanswered path under there and
`◐` means it is fully answered and its paths disagree.

`↑` `↓` move, `Enter` acts on the row under the cursor, and `Ctrl-C` quits lane — from
anywhere, and always safely: every question comes before the first irreversible step.

## Or drive it from a script

Everything the menu does, a subcommand does — and it is the same code underneath, not a
second implementation:

```bash
lane open --project acme --description "Fix the pager" --branch-name bugfix/pager
lane list --json | jq -r '.[] | select(.merged) | .slug'
lane enter acme/fix-the-pager
lane close acme/fix-the-pager --yes --keep-branch
lane doctor --json
lane config set editor zed
```

`lane --help` lists them; `lane <command> --help` lists that command's flags. Three
things worth knowing before you script it:

- **`--json` puts one JSON document on stdout and nothing else** — every `✓`, spinner
  and refusal goes to stderr, so a pipe is always parseable.
- **A missing flag is asked for if you have a terminal, and refused by name if you do
  not.** lane never sits waiting for an answer nothing can give it.
- **The editor does not launch from a subcommand** unless you pass `--launch-editor`.

Exit codes: `0` done · `1` refused · `2` bad flags · `3` needs an answer, no terminal ·
`4` no such lane · `130` interrupted.

## Configure

`~/.config/lane/config.toml` — `%APPDATA%\lane\config.toml` on Windows — three settings:

```toml
projects_root = "/Users/you/Projects"   # one git repository per subfolder
lanes_root = "/Users/you/Lanes"         # where lanes are parked
editor = "cursor"                       # code, zed, idea, subl...
```

`LANE_PROJECTS_ROOT`, `LANE_LANES_ROOT` and `LANE_EDITOR` override the file. What to do
with each project's ignored paths lives beside it in `prepare.toml`. **config →
preparation** opens the very screen above, over every project at once, so changing an
answer is the same one keystroke wherever you came from; **config → commands** is where
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
