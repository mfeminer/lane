"""What changed between versions.

Its own action precisely so the config upgrade notice can stay one short line.
"""

from __future__ import annotations

from lane import __version__
from lane.context import Context

# 0.0.1 is the first release, so its entry describes the tool as a whole rather
# than a diff against anything. Later versions get proper entries.
ENTRIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "0.0.2",
        "the lane listing became a screen you act from",
        (
            "Closing a lane deletes its local branch, and the summary says so before you "
            "confirm. A squash-merged lane used to leak its branch: `git branch -d` refuses "
            "when the commits exist nowhere in the base, which is the exact case the pull "
            "request check exists for.",
            "'lanes' replaces 'list', 'enter' and 'close'. The listing is where you look at "
            "your lanes and where you act on them; the two used to be separate menu entries "
            "and separate widgets, and nothing connected a row to the thing that acted on it.",
            "Arrow keys move a cursor over the rows. Enter offers what you can do with the "
            "row under the cursor — enter it, or close it — instead of a list of every lane "
            "crossed with every verb.",
            "No new keys: the table binds arrows, Enter and Ctrl-C, exactly as every other "
            "prompt does. Going back is still a row you can see.",
            "State and pull request state get the room now, because they answer the question "
            "the listing exists for: which of these can I close, and what is stopping the "
            "rest. The branch moved into the panel under the table — it was the lane name "
            "with a prefix in front of it.",
            "Pull request state no longer holds up the screen. Everything git can answer "
            "locally is drawn immediately and the 'pr' column fills in behind you.",
            "When `gh` cannot be asked, the column says 'unknown' rather than 'none', and "
            "the panel names the command that fixes it.",
            "Closing leaves you in the listing, one row shorter, so closing several lanes "
            "no longer means a round trip to the menu for each one.",
            "A lane's description is only shown when the lane name could not keep all of it "
            "— it was being printed twice under a different set of hyphens.",
            "Opening a lane no longer trusts a stale `origin/HEAD`: it used to be read "
            "before ever asking the remote, so a repository whose default branch changed "
            "since it was cloned kept getting a new lane started from the old one.",
        ),
    ),
    (
        "0.0.1",
        "first release",
        (
            "Open a lane per task: its own worktree, branch and editor window, so several "
            "pieces of work run side by side without colliding.",
            "Interactive throughout: one menu, no subcommands.",
            "Branch naming is decided per lane while opening it, not globally.",
            "New branches are created with no upstream, so a bare `git push` inside a lane "
            "cannot land on the default branch.",
            "Closing a lane checks for uncommitted files, unpushed commits and whether the "
            "work reached the default branch, and asks GitHub about the pull request.",
            "A squashed or rebased pull request counts as merged even though git's ancestry "
            "check disagrees.",
            "Everything a close needs to know is asked before anything is removed, so "
            "backing out is always a clean no-op.",
            "Commits stranded on a detached HEAD are offered a wip/ branch before removal.",
            "The lane listing shows age and pull request state, and stays fast with many "
            "lanes by collecting status concurrently.",
            "Distributed as a single self-contained binary; doctor reports which copy is "
            "running and fingerprints it.",
        ),
    ),
)


def run(context: Context) -> None:
    ui = context.ui
    ui.heading("lane changelog")
    for version, summary, bullets in ENTRIES:
        ui.blank()
        marker = "  (this version)" if version == __version__ else ""
        ui.info(f"  {version} — {summary}{marker}")
        for bullet in bullets:
            ui.detail(f"  {bullet}")
    ui.blank()
