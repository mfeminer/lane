"""Closing a lane: the three checks, the pull request, and the rescue.

The stubbed `GitHubClient` controls the pull request answer completely, because the
close path decides from that answer alone and never probes the environment
separately. That is what makes one stub sufficient.
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from lane.actions import close_lane
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.github.client import CannotTell, NoPullRequest, NotApplicable, PullRequest, found
from lane.lanes import LaneMeta, LaneStore
from lane.state import StateStore
from lane.ui.seam import Abandoned
from tests.conftest import Origin, build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient

GITHUB_URL = "git@github.com:acme/thing.git"


def _context(
    ui: FakeUi,
    projects_root: Path,
    lanes_root: Path,
    github: StubGitHubClient,
) -> Context:
    return Context(
        ui=ui,
        git=CliGitBackend(),
        github=github,
        environment=FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor"),
        config_store=ConfigStore(lanes_root.parent / "cfg"),
        state_store=StateStore(lanes_root.parent / "st"),
    )


@pytest.fixture
def lane_setup(projects_root: Path, lanes_root: Path) -> tuple[Origin, Path, LaneStore]:
    origin, clone = build_repo(projects_root / "_b", default_branch="main")
    repo = projects_root / "thing"
    clone.rename(repo)
    git(["remote", "set-url", "origin", str(origin.path)], cwd=repo)
    return origin, repo, LaneStore(lanes_root)


def _open_branch_lane(
    repo: Path, store: LaneStore, name: str = "mylane", branch: str = "feature/x"
) -> Path:
    backend = CliGitBackend()
    path = store.lane_path("thing", name)
    backend.add_worktree_new_branch(repo, path, branch, "origin/main")
    store.write_meta(
        "thing",
        name,
        LaneMeta(
            description=f"task {name}",
            base="main",
            created="2026-08-01 09:00",
            repo=str(repo),
            start=backend.head_commit(path),
        ),
    )
    return path


def _open_detached_lane(repo: Path, store: LaneStore, name: str = "detlane") -> Path:
    backend = CliGitBackend()
    path = store.lane_path("thing", name)
    backend.add_worktree_detached(repo, path, "origin/main")
    store.write_meta(
        "thing",
        name,
        LaneMeta(
            description="detached task",
            base="main",
            created="2026-08-01 09:00",
            repo=str(repo),
            start=backend.head_commit(path),
        ),
    )
    return path


def _close(context: Context, store: LaneStore, name: str = "mylane") -> None:
    """Close the lane the listing would have had the cursor on.

    `close` takes a lane rather than asking for one: choosing happens in the
    listing now, which shows the same names with the status that tells you which
    one you meant. See ADR 0002.
    """
    chosen = next(lane for lane in store.list_lanes() if lane.name == name)
    close_lane.close(context, chosen)


def _commit(worktree: Path, name: str, message: str) -> str:
    (worktree / name).write_text(f"{message}\n")
    git(["add", "-A"], cwd=worktree)
    git(["commit", "--quiet", "-m", message], cwd=worktree)
    return git(["rev-parse", "HEAD"], cwd=worktree).strip()


# -- I14, I15, I16: the three checks ---------------------------------------------


def test_uncommitted_files_are_reported_and_block(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    (lane / "scratch.txt").write_text("unsaved\n")

    ui = FakeUi([False])  # decline the close
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert ui.said("uncommitted")
    assert ui.said("discards")
    assert lane.is_dir(), "declining leaves the lane alone"


def test_unpushed_commits_are_reported_as_never_pushed(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "work.txt", "some work")

    ui = FakeUi([False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert ui.said("never pushed")
    assert ui.said("1 commit")


def test_unpushed_commits_are_reported_against_the_upstream_when_there_is_one(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "pushed.txt", "pushed")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)
    _commit(lane, "later.txt", "not pushed")

    ui = FakeUi([False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert ui.said("ahead of origin/feature/x")


def test_a_clean_merged_lane_reports_no_issues(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert ui.said("Lane is clear")
    assert ui.said("Working tree is clean")
    assert ui.said("Nothing left to push")
    assert not lane.exists()


# -- I17: the squash-merge false negative, the reason this feature exists ---------


def test_a_merged_pull_request_counts_as_clean_even_though_git_disagrees(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """A squash or rebase merge leaves the lane's commits nowhere in the base."""
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "feature.txt", "the feature")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)
    # The remote moves on with an unrelated commit — a squashed merge, in effect.
    origin.advance("squashed the feature")
    CliGitBackend().fetch_prune(repo)

    # git's own check must disagree, or this test proves nothing.
    assert not CliGitBackend().status(lane, "main").merged

    merged_pr = found(PullRequest(number=42, state="MERGED", url="https://github.com/a/b/pull/42"))
    ui = FakeUi([True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(merged_pr)), store, "mylane")

    assert ui.said("Lane is clear"), "a MERGED PR must make this a clean close"
    assert ui.said("squashed or rebased")
    assert ui.said("#42")
    assert not lane.exists()


def test_a_lane_whose_remote_branch_was_deleted_on_merge_is_not_called_never_pushed(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """The reported fault: `✓ PR merged` and `! never pushed`, about the same lane.

    Merging with *delete branch* — the default on most repositories — removes
    `origin/<branch>`, so `@{u}` stops resolving and the unpushed count falls back to
    counting against `origin/main`, where a squash merge left none of the lane's
    commits. Neither fact says the branch was never pushed, and neither is a reason to
    hold the lane open. This is the same false negative the pull request check already
    exists to correct, reached through the check next door.
    """
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    landed = _commit(lane, "feature.txt", "the feature")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)
    origin.advance("squashed the feature")
    origin.delete_branch("feature/x")
    CliGitBackend().fetch_prune(repo)

    # The shape of the bug, before anything is asserted about what lane says.
    status = CliGitBackend().status(lane, "main")
    assert status.upstream is None, "the remote-tracking ref went with the merge"
    assert status.unpushed_count == 1, "and the count fell back to origin/main"

    merged = found(
        PullRequest(
            number=42, state="MERGED", url="https://github.com/a/b/pull/42", head_oid=landed
        )
    )
    ui = FakeUi([True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(merged)), store, "mylane")

    assert not ui.said("never pushed"), "it was pushed — that is where PR #42 came from"
    assert ui.said("Nothing left to push")
    assert ui.said("Lane is clear")
    assert not lane.exists()


def test_commits_made_after_the_merge_still_block(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """What keeps the fix above from excusing work that has not landed.

    A merged pull request is not a blanket amnesty for everything on the branch. The
    commits it carried are safe; anything committed afterwards exists in this worktree
    and nowhere else, and closing the lane would take it away.
    """
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    landed = _commit(lane, "feature.txt", "the feature")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)
    origin.advance("squashed the feature")
    origin.delete_branch("feature/x")
    CliGitBackend().fetch_prune(repo)
    _commit(lane, "afterthought.txt", "a fix-up nobody has seen")

    merged = found(PullRequest(number=42, state="MERGED", url="u42", head_oid=landed))
    ui = FakeUi([False])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(merged)), store, "mylane")

    assert ui.said("1 commit(s) made after PR #42 merged")
    assert ui.said("holding this lane open")
    assert lane.is_dir(), "declining leaves the unlanded commit where it is"


def test_a_branch_amended_after_its_merge_is_refused_rather_than_guessed_at(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Rebase or amend after the merge and the commit that landed is gone from here.

    How much of this branch the pull request carried then cannot be known locally, and
    "cannot tell" is refused for the same reason an unreachable `gh` is: the answer is
    what the close decides on, and a guess in its place risks the commits.
    """
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "feature.txt", "the feature")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)
    origin.advance("squashed the feature")
    origin.delete_branch("feature/x")
    CliGitBackend().fetch_prune(repo)
    git(["commit", "--quiet", "--amend", "-m", "the feature, reworded"], cwd=lane)

    # The pull request merged from a commit this branch no longer has.
    merged = found(PullRequest(number=42, state="MERGED", url="u42", head_oid="0" * 40))
    ui = FakeUi([False])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(merged)), store, "mylane")

    assert ui.said("Cannot tell what PR #42 carried")
    assert ui.said("holding this lane open")
    assert lane.is_dir()


# -- I18: open, closed and missing pull requests block ---------------------------


def test_an_open_pull_request_blocks_and_shows_its_url(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "wip.txt", "work in progress")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)

    open_pr = found(PullRequest(number=7, state="OPEN", url="https://github.com/a/b/pull/7"))
    ui = FakeUi([False])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(open_pr)), store, "mylane")

    assert ui.said("still open")
    assert ui.said("https://github.com/a/b/pull/7")
    assert ui.said("holding this lane open")
    assert lane.is_dir()


def test_an_open_follow_up_blocks_even_though_an_earlier_one_merged(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """A lane's branch can carry a history of pull requests, and none of it is dropped.

    The earlier one landing does not make the lane closeable: the open follow-up is
    work in flight, and closing over it would take the branch it lives on. Both are
    reported — the merged one as context, the open one as the thing in the way.
    """
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    landed = _commit(lane, "feature.txt", "the feature")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/x"], cwd=lane)
    origin.advance("squashed the feature")
    CliGitBackend().fetch_prune(repo)
    _commit(lane, "followup.txt", "the fix-up")
    git(["push", "--quiet", "origin", "feature/x"], cwd=lane)

    history = found(
        PullRequest(
            number=41, state="MERGED", url="https://github.com/a/b/pull/41", head_oid=landed
        ),
        PullRequest(number=42, state="OPEN", url="https://github.com/a/b/pull/42"),
    )
    ui = FakeUi([False])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(history)), store, "mylane")

    assert ui.said("PR #42 is still open")
    assert ui.said("https://github.com/a/b/pull/41"), "the earlier one is not dropped"
    assert ui.said("holding this lane open")
    assert not ui.said("Lane is clear")
    assert lane.is_dir()


def test_every_branch_the_lane_used_is_deleted_not_only_the_last_one(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """A lane's branches go with the lane, and a lane can have used several.

    Leaving the earlier ones behind is how a repository fills up with dead branches
    after every successful close — the same fault deleting the current branch exists to
    prevent, one branch to the left. They are read from the worktree's reflog while it
    is still there: removing it takes that record with it.
    """
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, branch="feature/first")
    git(["switch", "--quiet", "-c", "feature/second"], cwd=lane)

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    backend = CliGitBackend()
    assert not backend.branch_exists(repo, "feature/second")
    assert not backend.branch_exists(repo, "feature/first"), "the one it started on goes too"
    assert ui.said("feature/first"), "and the summary said so before removing anything"


def _lane_with_an_unmerged_second_branch(repo: Path, store: LaneStore) -> Path:
    """A lane standing on a clean branch, with unique work left on one it used earlier."""
    lane = _open_branch_lane(repo, store, branch="feature/first")
    git(["switch", "--quiet", "-c", "feature/second"], cwd=lane)
    _commit(lane, "abandoned.txt", "work nobody took")
    git(["switch", "--quiet", "feature/first"], cwd=lane)
    return lane


def test_an_unmerged_branch_the_lane_used_is_not_force_deleted_without_permission(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """git's refusal to `-d` a branch holding unique work is the safety net here too.

    Overriding it is the user's call, asked in the same pass as every other question and
    before anything is removed — so declining leaves the branch exactly where it was,
    with the command to remove it by hand.
    """
    _, repo, store = lane_setup
    _lane_with_an_unmerged_second_branch(repo, store)

    ui = FakeUi([True, False])  # close it; but do not force the unmerged one
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    backend = CliGitBackend()
    assert not backend.branch_exists(repo, "feature/first"), "the lane's own branch still goes"
    assert backend.branch_exists(repo, "feature/second"), "the unmerged one was declined"
    assert ui.said("not merged")
    assert ui.said("Branch kept: feature/second")


def test_an_unmerged_branch_the_lane_used_is_deleted_once_permission_is_given(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    _lane_with_an_unmerged_second_branch(repo, store)

    ui = FakeUi([True, True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert not CliGitBackend().branch_exists(repo, "feature/second")
    assert ui.said("Branch deleted: feature/second")


def test_a_closed_pull_request_blocks_and_shows_its_url(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "abandoned.txt", "abandoned work")

    closed = found(PullRequest(number=9, state="CLOSED", url="https://github.com/a/b/pull/9"))
    ui = FakeUi([False])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(closed)), store, "mylane")

    assert ui.said("closed without being merged")
    assert ui.said("/pull/9")


def test_no_pull_request_blocks_without_a_url(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    _commit(lane, "orphan.txt", "no pr for this")

    ui = FakeUi([False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert ui.said("no pull request exists")
    assert not ui.said("http")


# -- I19, I20: gh missing refuses; a non-GitHub remote still closes ---------------


def test_a_github_lane_is_refused_when_gh_is_missing_with_a_usable_message(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)

    cannot = CannotTell(
        reason="gh-missing", remedy="brew install gh", detail="the GitHub CLI is not installed"
    )
    ui = FakeUi([])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(cannot)), store, "mylane")

    assert ui.said("cannot verify")
    assert ui.said("brew install gh")
    assert lane.is_dir(), "a lane that cannot be checked is never removed"


def test_a_github_lane_is_refused_when_gh_is_logged_out(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)

    cannot = CannotTell(
        reason="gh-logged-out", remedy="gh auth login", detail="gh is installed but not logged in"
    )
    ui = FakeUi([])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(cannot)), store, "mylane")

    assert ui.said("gh auth login")
    assert lane.is_dir()


def test_a_lane_with_a_non_github_remote_still_closes(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Only GitHub-backed lanes need gh. Everything else proceeds on git's evidence."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)

    ui = FakeUi([True])
    github = StubGitHubClient(NotApplicable("not-github"))
    _close(_context(ui, projects_root, lanes_root, github), store, "mylane")

    assert not lane.exists(), "the close must succeed without gh"


# -- I22: the detached-HEAD rescue -----------------------------------------------


def test_a_detached_lane_with_unpushed_commits_is_offered_a_wip_branch_that_survives(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_detached_lane(repo, store, "rescueme")
    stranded = _commit(lane, "precious.txt", "would be stranded")

    # confirm close, then confirm the rescue
    ui = FakeUi([True, True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "rescueme")

    assert ui.said("unreachable")
    assert not lane.exists()
    backend = CliGitBackend()
    assert backend.branch_exists(repo, "wip/rescueme"), "the rescue branch must survive"
    assert git(["rev-parse", "wip/rescueme"], cwd=repo).strip() == stranded


def test_declining_the_rescue_still_closes(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_detached_lane(repo, store, "norescue")
    _commit(lane, "meh.txt", "do not care")

    ui = FakeUi([True, False])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "norescue")

    assert not lane.exists()
    assert not CliGitBackend().branch_exists(repo, "wip/norescue")


def test_a_clean_detached_lane_is_not_offered_a_rescue(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_detached_lane(repo, store, "cleandet")

    ui = FakeUi([True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "cleandet")

    assert not lane.exists()
    assert not ui.said("unreachable")


# -- I21, I23, I24: everything asked before anything is removed ------------------


def test_the_summary_spells_out_what_is_about_to_be_removed(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)

    ui = FakeUi([False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "mylane"
    )

    assert ui.said("About to remove")
    assert ui.said(str(lane))
    assert ui.said("feature/x")


def test_abandoning_the_confirmation_changes_nothing(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store)
    (lane / "keep.txt").write_text("precious\n")

    ui = FakeUi([FakeUi.ABANDON])
    with pytest.raises(Abandoned):
        _close(
            _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())),
            store,
            "mylane",
        )

    assert lane.is_dir()
    assert (lane / "keep.txt").exists()
    assert store.metadata_file("thing", "mylane").exists()


def test_permission_to_force_delete_is_asked_before_the_worktree_is_gone(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Declining must leave the branch AND have asked before removal, not after."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "unmerged", "feature/unmerged")
    _commit(lane, "work.txt", "unmerged work")

    asked_while_present: list[bool] = []

    class Watching(FakeUi):
        def confirm(self, title, *, default=False, on_render=None):  # type: ignore[no-untyped-def]
            if "delete it anyway" in title.lower():
                asked_while_present.append(lane.exists())
            return super().confirm(title, default=default, on_render=on_render)

    ui = Watching([True, False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())),
        store,
        "unmerged",
    )

    assert asked_while_present == [True], "asked before the worktree was removed"
    assert not lane.exists()
    assert CliGitBackend().branch_exists(repo, "feature/unmerged"), "declining keeps the branch"


def test_agreeing_to_force_delete_removes_the_branch(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "gone", "feature/gone")
    _commit(lane, "work.txt", "unmerged work")

    ui = FakeUi([True, True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "gone"
    )

    assert not lane.exists()
    assert not CliGitBackend().branch_exists(repo, "feature/gone")


# -- I25, I26, I27: what execution does and does not touch -----------------------


def test_a_merged_branch_is_deleted_without_being_asked(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """git's own -d check passes, so there is nothing to ask about."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "merged", "feature/merged")

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "merged"
    )

    assert not lane.exists()
    assert not CliGitBackend().branch_exists(repo, "feature/merged")


def test_a_wip_branch_created_by_the_rescue_is_never_deleted(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Deleting it would defeat the entire purpose of the rescue."""
    _, repo, store = lane_setup
    lane = _open_detached_lane(repo, store, "keepwip")
    _commit(lane, "x.txt", "stranded")

    ui = FakeUi([True, True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "keepwip")

    assert CliGitBackend().branch_exists(repo, "wip/keepwip")


def test_closing_tidies_up_the_metadata_and_empty_directories(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    _open_branch_lane(repo, store, "only", "feature/only")

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "only"
    )

    assert not store.metadata_file("thing", "only").exists()
    assert not store.project_dir("thing").exists()
    assert store.list_lanes() == []


def test_closing_a_dirty_lane_after_confirmation_discards_it(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """The user was warned and said yes; git's refusal is bypassed only here."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "dirty", "feature/dirty")
    (lane / "scratch.txt").write_text("goodbye\n")

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "dirty"
    )

    assert not lane.exists()


def test_closing_a_freshly_opened_lane_does_not_claim_its_work_reached_the_base(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """It has no work. Saying "every commit is in origin/main" is vacuously true
    and reads as reassurance the user has not earned."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "untouched", "chore/untouched")

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())),
        store,
        "untouched",
    )

    assert ui.said("no commits of its own")
    assert not ui.said("Every commit is in")
    assert ui.said("Lane is clear"), "and it must still be a clean close"
    assert not lane.exists()


def test_closing_a_lane_whose_commits_reached_the_base_says_so(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "did-work", "feature/did-work")
    _commit(lane, "work.txt", "real work")
    git(["push", "--quiet", "origin", "feature/did-work:main"], cwd=lane)
    CliGitBackend().fetch_prune(repo)

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())),
        store,
        "did-work",
    )

    assert ui.said("Every commit is in origin/main")
    assert not lane.exists()


# -- the local branch goes with the lane -----------------------------------------


def test_a_squash_merged_lane_has_its_local_branch_deleted(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """The case this whole feature exists for, and it used to leak the branch.

    A squash merge leaves the lane's commits nowhere in the base, so `git branch -d`
    refuses. lane treated that refusal as "keep it" and said nothing useful, so
    branches piled up after every successful close.
    """
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "squashed", "feature/squashed")
    _commit(lane, "work.txt", "the feature")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/squashed"], cwd=lane)
    origin.advance("squashed the feature")
    CliGitBackend().fetch_prune(repo)
    assert not CliGitBackend().status(lane, "main").merged, (
        "git must disagree, or this proves nothing"
    )

    merged_pr = found(PullRequest(number=7, state="MERGED", url="https://github.com/a/b/pull/7"))
    ui = FakeUi([True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(merged_pr)), store, "squashed")

    assert not lane.exists()
    assert not CliGitBackend().branch_exists(repo, "feature/squashed"), "the branch must go too"


def test_the_summary_warns_that_the_branch_will_be_deleted(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Removing a branch is not something to discover afterwards."""
    _, repo, store = lane_setup
    _open_branch_lane(repo, store, "warned", "feature/warned")

    ui = FakeUi([False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "warned"
    )

    transcript = ui.transcript.lower()
    assert "feature/warned" in ui.transcript
    assert "delete" in transcript, transcript


def test_a_merged_lane_does_not_ask_twice_about_its_branch(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """With evidence the work landed, deleting the branch needs no second question."""
    origin, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "noask", "feature/noask")
    _commit(lane, "w.txt", "work")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/noask"], cwd=lane)
    origin.advance("squashed")
    CliGitBackend().fetch_prune(repo)

    merged_pr = found(PullRequest(number=8, state="MERGED", url="u"))
    # Only two answers scripted: pick the lane, confirm the close. A third question
    # would exhaust the script and fail.
    ui = FakeUi([True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient(merged_pr)), store, "noask")

    assert not CliGitBackend().branch_exists(repo, "feature/noask")


def test_an_unmerged_branch_is_still_only_deleted_with_permission(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """No evidence it landed, so deleting it would destroy work. Declining keeps it."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "risky", "feature/risky")
    _commit(lane, "work.txt", "unpushed work")

    ui = FakeUi([True, False])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "risky"
    )

    assert not lane.exists()
    assert CliGitBackend().branch_exists(repo, "feature/risky")
    assert ui.said("kept")


def test_a_detached_lane_says_nothing_about_deleting_a_branch(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    _open_detached_lane(repo, store, "nobranch")

    ui = FakeUi([True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "nobranch")

    assert not ui.said("will be deleted")


# -- the slow half is after the last question, and it says so --------------------


def _steps(ui: FakeUi) -> list[str]:
    return [told.text for told in ui.told if told.kind == "progress"]


def test_removing_the_worktree_and_the_branch_announce_themselves(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Everything slow enough to notice shows a spinner — including the steps that
    come *after* the last question. Removing a worktree of a few thousand files is
    the longest thing a close does, and an unannounced pause there reads as a hang."""
    _, repo, store = lane_setup
    _open_branch_lane(repo, store, "slow", "feature/slow")

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "slow"
    )

    steps = _steps(ui)
    assert any("removing the worktree" in step.lower() for step in steps), steps
    assert any("feature/slow" in step for step in steps), steps


def test_the_removal_is_announced_after_the_last_question(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """The gap the user sees starts at `y`, so the spinner has to start there too."""
    _, repo, store = lane_setup
    _open_branch_lane(repo, store, "ordered", "feature/ordered")

    ui = FakeUi([True])
    _close(
        _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())), store, "ordered"
    )

    summary = next(i for i, told in enumerate(ui.told) if told.text == "About to remove")
    removal = next(
        i
        for i, told in enumerate(ui.told)
        if told.kind == "progress" and "removing the worktree" in told.text.lower()
    )
    assert removal > summary


def test_parking_the_rescue_branch_announces_itself(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    _, repo, store = lane_setup
    lane = _open_detached_lane(repo, store, "parked")
    _commit(lane, "precious.txt", "would be stranded")

    ui = FakeUi([True, True])
    _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "parked")

    steps = _steps(ui)
    assert any("parking" in step.lower() and "wip/parked" in step for step in steps), steps


# -- Ctrl-C during the removal ----------------------------------------------------


class InterruptingUi(FakeUi):
    """Presses Ctrl-C the moment a named step starts.

    A real SIGINT to this process, because that is what the terminal sends and what
    the deferral is written against. The sleep lets it land: the C handler only
    flags it, and the Python one runs at the next bytecode boundary.
    """

    def __init__(self, answers: Sequence[object], *, at: str) -> None:
        super().__init__(answers)
        self._at = at

    def progress[T](self, text: str, work: Callable[[], T]) -> T:
        if self._at in text.lower():
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.01)
        return super().progress(text, work)


def test_ctrl_c_during_the_removal_does_not_leave_it_half_done(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """A partly deleted working copy is a state nothing in lane can describe, let
    alone repair. So the step finishes and the interrupt is raised afterwards."""
    _, repo, store = lane_setup
    lane = _open_branch_lane(repo, store, "stopme", "feature/stopme")

    ui = InterruptingUi([True], at="removing the worktree")
    with pytest.raises(KeyboardInterrupt):
        _close(
            _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())),
            store,
            "stopme",
        )

    assert not lane.exists()
    assert store.list_lanes() == []
    # The whole phase is deferred, not only the removal: a lane whose worktree is
    # gone but whose branch survives is exactly the mess this avoids.
    assert not CliGitBackend().branch_exists(repo, "feature/stopme")


def test_ctrl_c_during_the_removal_says_it_landed(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """A Ctrl-C that appears to do nothing reads as a hung program — which is the
    very thing deferring it is trying not to look like."""
    _, repo, store = lane_setup
    _open_branch_lane(repo, store, "tellme", "feature/tellme")

    ui = InterruptingUi([True], at="removing the worktree")
    with pytest.raises(KeyboardInterrupt):
        _close(
            _context(ui, projects_root, lanes_root, StubGitHubClient(NoPullRequest())),
            store,
            "tellme",
        )

    assert ui.said("finishing")
    # The way out of a step that turns out to take far longer than it implied.
    assert ui.said("ctrl-c again")


def test_the_rescue_is_covered_by_the_same_deferral(
    lane_setup: tuple[Origin, Path, LaneStore], projects_root: Path, lanes_root: Path
) -> None:
    """Interrupting between "worktree removed" and "commits parked" would strand
    exactly the work the rescue exists to save."""
    _, repo, store = lane_setup
    lane = _open_detached_lane(repo, store, "stopwip")
    stranded = _commit(lane, "precious.txt", "would be stranded")

    ui = InterruptingUi([True, True], at="parking")
    with pytest.raises(KeyboardInterrupt):
        _close(_context(ui, projects_root, lanes_root, StubGitHubClient()), store, "stopwip")

    backend = CliGitBackend()
    assert backend.branch_exists(repo, "wip/stopwip")
    assert git(["rev-parse", "wip/stopwip"], cwd=repo).strip() == stranded
    assert not lane.exists()
