"""The git backend, against real temporary repositories.

These are the seven Phase 0 criteria, now as the suite's permanent contract for
whatever implementation sits behind `GitBackend`.
"""

from __future__ import annotations

from pathlib import Path

from lane.git.backend import GitError
from lane.git.cli_backend import CliGitBackend
from tests.conftest import Origin, build_repo, git

# -- interrogation ---------------------------------------------------------------


def test_recognises_a_repository_and_a_plain_directory(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    assert backend.is_repository(clone)
    assert not backend.is_repository(tmp_path)
    assert not backend.is_repository(tmp_path / "nope")


def test_reports_git_version(backend: CliGitBackend) -> None:
    version = backend.version()
    assert version is not None
    assert "git version" in version


def test_reports_the_remote_url(backend: CliGitBackend, repo: tuple[Origin, Path]) -> None:
    origin, clone = repo
    assert backend.remote_url(clone) == str(origin.path)


def test_a_repository_without_a_remote_has_no_url(backend: CliGitBackend, tmp_path: Path) -> None:
    solo = tmp_path / "solo"
    git(["init", "--quiet", str(solo)])
    assert backend.remote_url(solo) is None


# -- default branch (F3, F4, F5) -------------------------------------------------


def test_default_branch_from_origin_head_on_main(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    _, clone = repo
    assert backend.default_branch(clone) == "main"


def test_default_branch_from_origin_head_on_master(
    backend: CliGitBackend, master_repo: tuple[Origin, Path]
) -> None:
    _, clone = master_repo
    assert backend.default_branch(clone) == "master"


def test_default_branch_prefers_main_over_a_coexisting_master(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    """`master` existing alongside `main` must not confuse the origin/HEAD read."""
    origin, clone = repo
    origin.create_branch("master")
    git(["fetch", "--quiet", "origin"], cwd=clone)

    assert backend.default_branch(clone) == "main"


def test_default_branch_recovers_from_a_stale_origin_head(
    backend: CliGitBackend, tmp_path: Path
) -> None:
    """`refs/remotes/origin/HEAD` is written once at clone time and does not follow
    the remote when its default branch changes later. A repository cloned back when
    the default was `master` must not keep reporting `master` forever just because
    that is what is still cached on disk — `set-head --auto` has to run and be
    trusted over the stale local symref, not only when the symref is entirely gone.
    """
    origin, clone = build_repo(tmp_path / "migrated", default_branch="master")
    git(["branch", "main", "master"], cwd=origin.path)
    git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=origin.path)

    # The clone's cached origin/HEAD is untouched by the remote's change — this is
    # the staleness the bug report described.
    assert (
        git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=clone).strip()
        == "origin/master"
    )

    # A real lane always fetches before resolving the base (open_lane._gather), which
    # is what brings refs/remotes/origin/main into existence for set-head to point at.
    backend.fetch_prune(clone)

    assert backend.default_branch(clone) == "main"


def test_default_branch_recovers_when_origin_head_is_missing(
    backend: CliGitBackend, dev_repo: tuple[Origin, Path]
) -> None:
    """`dev` is what the maintainer's primary repository uses, and it is exactly the
    case the reference implementation's main/master/develop probe misses."""
    _, clone = dev_repo
    git(["symbolic-ref", "--delete", "refs/remotes/origin/HEAD"], cwd=clone)

    # set-head --auto must recover it; the hardcoded probe would not.
    assert backend.default_branch(clone) == "dev"


def test_default_branch_falls_back_to_a_conventional_name(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    """origin/HEAD gone and the remote unreachable: main/master/develop is the last resort."""
    origin, clone = repo
    git(["symbolic-ref", "--delete", "refs/remotes/origin/HEAD"], cwd=clone)
    git(["remote", "set-url", "origin", str(origin.path) + "-gone"], cwd=clone)

    assert backend.default_branch(clone) == "main"


def test_default_branch_is_unknown_rather_than_guessed(
    backend: CliGitBackend, tmp_path: Path
) -> None:
    """Refusing to guess is the point: a wrong answer bases a lane on the wrong branch."""
    origin, clone = build_repo(tmp_path / "odd", default_branch="release-2024")
    git(["symbolic-ref", "--delete", "refs/remotes/origin/HEAD"], cwd=clone)
    git(["remote", "set-url", "origin", str(origin.path) + "-gone"], cwd=clone)

    assert backend.default_branch(clone) is None


def test_rev_parse_verify(backend: CliGitBackend, repo: tuple[Origin, Path]) -> None:
    _, clone = repo
    assert backend.rev_parse_verify(clone, "origin/main")
    assert not backend.rev_parse_verify(clone, "origin/nonexistent")


# -- ref name validation (F16) ---------------------------------------------------


def test_check_ref_format_defers_to_git(backend: CliGitBackend) -> None:
    assert backend.check_ref_format("feature/ok")
    assert backend.check_ref_format("a/b/c")
    assert not backend.check_ref_format("bad..name")
    assert not backend.check_ref_format("has space")
    assert not backend.check_ref_format("")
    # Cases where a library's own validator disagrees with git (see ADR 0001).
    assert not backend.check_ref_format("-leading")
    assert not backend.check_ref_format("HEAD")


# -- fetching (F6) ---------------------------------------------------------------


def test_fetch_prune_brings_commits_down_and_removes_deleted_branches(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    origin, clone = repo
    origin.create_branch("doomed")
    assert backend.fetch_prune(clone).ok
    assert backend.rev_parse_verify(clone, "origin/doomed")

    origin.delete_branch("doomed")
    origin.advance("moved on")

    result = backend.fetch_prune(clone)

    assert result.ok
    assert not backend.rev_parse_verify(clone, "origin/doomed")
    assert backend.status(clone, "main").merged  # local HEAD is now behind


def test_a_failing_fetch_is_reported_not_raised(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    """Being offline must not stop a close; it only makes merge state stale."""
    origin, clone = repo
    git(["remote", "set-url", "origin", str(origin.path) + "-gone"], cwd=clone)

    result = backend.fetch_prune(clone)

    assert not result.ok
    assert result.detail


# -- worktree lifecycle (F7, F8, F9, F13) ----------------------------------------


def test_worktree_on_a_new_branch_has_no_upstream(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    """The invariant: a bare `git push` in a lane cannot reach the default branch."""
    _, clone = repo
    lane = tmp_path / "lanes" / "feature-lane"

    backend.add_worktree_new_branch(clone, lane, "feature/thing", "origin/main")

    assert lane.is_dir()
    status = backend.status(lane, "main")
    assert status.branch == "feature/thing"
    assert status.upstream is None, "a new lane branch must not track anything"


def test_worktree_on_a_detached_head(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "detached-lane"

    backend.add_worktree_detached(clone, lane, "origin/main")

    status = backend.status(lane, "main")
    assert status.detached
    assert status.branch is None
    assert status.head_short


def test_worktree_on_an_existing_branch(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    backend.create_branch(clone, "already/here", "origin/main")
    lane = tmp_path / "lanes" / "existing"

    backend.add_worktree_existing_branch(clone, lane, "already/here")

    assert backend.status(lane, "main").branch == "already/here"


def test_creating_a_worktree_where_one_exists_fails_clearly(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "twice"
    backend.add_worktree_new_branch(clone, lane, "feature/one", "origin/main")

    try:
        backend.add_worktree_new_branch(clone, lane, "feature/two", "origin/main")
    except GitError as exc:
        assert str(exc)
    else:
        raise AssertionError("expected GitError")


def test_removing_a_clean_worktree_then_pruning(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "clean"
    backend.add_worktree_new_branch(clone, lane, "feature/clean", "origin/main")

    backend.remove_worktree(clone, lane)
    backend.prune_worktrees(clone)

    assert not lane.exists()
    assert str(lane) not in git(["worktree", "list", "--porcelain"], cwd=clone)


def test_git_refuses_to_remove_a_dirty_worktree_unless_forced(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    """This refusal is the safety net lane inherits by shelling out to git."""
    _, clone = repo
    lane = tmp_path / "lanes" / "dirty"
    backend.add_worktree_new_branch(clone, lane, "feature/dirty", "origin/main")
    (lane / "untracked.txt").write_text("unsaved work\n")

    try:
        backend.remove_worktree(clone, lane)
    except GitError:
        pass
    else:
        raise AssertionError("git should refuse to discard uncommitted work")
    assert lane.exists(), "the worktree must survive a refused removal"

    backend.remove_worktree(clone, lane, force=True)
    assert not lane.exists()


# -- status (F10, F11, F12) ------------------------------------------------------


def test_status_counts_uncommitted_and_untracked_files(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "s"
    backend.add_worktree_new_branch(clone, lane, "feature/s", "origin/main")
    assert backend.status(lane, "main").dirty_count == 0

    (lane / "file0.txt").write_text("modified\n")
    (lane / "brand-new.txt").write_text("new\n")

    status = backend.status(lane, "main")
    assert status.dirty_count == 2
    listed = backend.dirty_files(lane)
    assert any("file0.txt" in line for line in listed)
    assert any("brand-new.txt" in line for line in listed)


def test_unpushed_counted_against_origin_base_when_there_is_no_upstream(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "u"
    backend.add_worktree_new_branch(clone, lane, "feature/u", "origin/main")

    _commit(lane, "work.txt", "first")
    _commit(lane, "work2.txt", "second")

    status = backend.status(lane, "main")
    assert status.upstream is None
    assert status.unpushed_count == 2
    assert len(backend.log_oneline(lane, "origin/main..HEAD")) == 2


def test_unpushed_counted_against_the_upstream_when_there_is_one(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "up"
    backend.add_worktree_new_branch(clone, lane, "feature/up", "origin/main")
    _commit(lane, "pushed.txt", "pushed work")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/up"], cwd=lane)

    assert backend.status(lane, "main").unpushed_count == 0

    _commit(lane, "later.txt", "after pushing")

    status = backend.status(lane, "main")
    assert status.upstream == "origin/feature/up"
    assert status.unpushed_count == 1


def test_merged_is_true_when_head_is_an_ancestor_of_origin_base(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "m"
    backend.add_worktree_detached(clone, lane, "origin/main")

    assert backend.status(lane, "main").merged

    _commit(lane, "ahead.txt", "not merged")
    assert not backend.status(lane, "main").merged


# -- branches (F14, F15) ---------------------------------------------------------


def test_create_branch_at_a_commit(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    """This is what parks wip/<lane> before a detached lane is removed."""
    _, clone = repo
    lane = tmp_path / "lanes" / "wip-source"
    backend.add_worktree_detached(clone, lane, "origin/main")
    head = _commit(lane, "rescued.txt", "would be stranded")

    backend.create_branch(clone, "wip/rescue", head)

    assert backend.branch_exists(clone, "wip/rescue")
    assert git(["rev-parse", "wip/rescue"], cwd=clone).strip() == head


def test_deleting_a_merged_branch_succeeds_and_an_unmerged_one_is_refused(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    """git applies the merged check; lane never reimplements it."""
    _, clone = repo
    backend.create_branch(clone, "merged/branch", "origin/main")
    assert backend.delete_branch(clone, "merged/branch")
    assert not backend.branch_exists(clone, "merged/branch")

    lane = tmp_path / "lanes" / "unmerged"
    backend.add_worktree_new_branch(clone, lane, "feature/unmerged", "origin/main")
    _commit(lane, "work.txt", "unmerged work")
    backend.remove_worktree(clone, lane, force=True)

    assert not backend.delete_branch(clone, "feature/unmerged")
    assert backend.branch_exists(clone, "feature/unmerged")

    assert backend.delete_branch(clone, "feature/unmerged", force=True)
    assert not backend.branch_exists(clone, "feature/unmerged")


def test_head_commit(backend: CliGitBackend, repo: tuple[Origin, Path]) -> None:
    _, clone = repo
    assert backend.head_commit(clone) == git(["rev-parse", "HEAD"], cwd=clone).strip()


# -- the environment is pinned (F18) ---------------------------------------------


def test_output_is_not_affected_by_the_users_locale_or_config(
    backend: CliGitBackend, repo: tuple[Origin, Path], monkeypatch: object
) -> None:
    """A user's git config must not change what the backend parses."""
    _, clone = repo
    # status.branch and similar niceties change porcelain-adjacent output.
    git(["config", "status.branch", "true"], cwd=clone)
    git(["config", "log.date", "relative"], cwd=clone)
    git(["config", "core.quotePath", "true"], cwd=clone)

    (clone / "ünïcode näme.txt").write_text("x\n")

    status = backend.status(clone, "main")
    assert status.dirty_count == 1
    # The path must come back readable, not as \303\274 escapes.
    assert any("nicode" in line or "ünïcode" in line for line in backend.dirty_files(clone))


def _commit(worktree: Path, name: str, message: str) -> str:
    (worktree / name).write_text(f"{message}\n")
    git(["add", "-A"], cwd=worktree)
    git(["commit", "--quiet", "-m", message], cwd=worktree)
    return git(["rev-parse", "HEAD"], cwd=worktree).strip()


def test_a_repository_is_recognised_through_a_differently_cased_path(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    """macOS and Windows filesystems are case-insensitive.

    A user who types `/users/me/projects` reaches the same directory as
    `/Users/me/Projects`, and git reports the on-disk case back. Comparing the two
    as strings made every project silently vanish.
    """
    _, clone = repo
    swapped = Path(str(clone).upper())
    if not swapped.is_dir():
        # A genuinely case-sensitive filesystem; there is nothing to test here.
        return

    assert backend.is_repository(swapped)


def test_a_repository_is_recognised_through_a_path_with_redundant_separators(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    _, clone = repo
    assert backend.is_repository(Path(f"{clone}//."))


def test_a_subdirectory_of_a_repository_is_not_itself_a_repository(
    backend: CliGitBackend, repo: tuple[Origin, Path]
) -> None:
    """Otherwise every folder inside a repo would look like a project."""
    _, clone = repo
    inner = clone / "subdir"
    inner.mkdir()

    assert not backend.is_repository(inner)


# -- "merged" must mean the lane's work landed, not that it has no work ------------


def test_a_fresh_lane_has_no_commits_of_its_own(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    """A lane opened a minute ago sits exactly at origin/<base>.

    HEAD *is* an ancestor of origin/<base> — vacuously, because they are the same
    commit — so an ancestry check alone says "merged" about a lane that has never
    had anything to merge. The count of commits ahead of the base is what tells them
    apart.
    """
    _, clone = repo
    lane = tmp_path / "lanes" / "fresh"
    backend.add_worktree_new_branch(clone, lane, "feature/fresh", "origin/main")

    status = backend.status(lane, "main")

    assert status.ahead_of_base == 0
    assert not status.has_own_commits
    assert status.merged, "the ancestry fact is still true"


def test_a_lane_with_work_reports_commits_ahead_of_the_base(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    _, clone = repo
    lane = tmp_path / "lanes" / "working"
    backend.add_worktree_new_branch(clone, lane, "feature/working", "origin/main")

    _commit(lane, "one.txt", "first")
    _commit(lane, "two.txt", "second")

    status = backend.status(lane, "main")
    assert status.ahead_of_base == 2
    assert status.has_own_commits
    assert not status.merged


def test_commits_ahead_of_base_are_counted_against_the_base_not_the_upstream(
    backend: CliGitBackend, repo: tuple[Origin, Path], tmp_path: Path
) -> None:
    """Pushing does not make the work part of the base branch."""
    _, clone = repo
    lane = tmp_path / "lanes" / "pushed"
    backend.add_worktree_new_branch(clone, lane, "feature/pushed", "origin/main")
    _commit(lane, "work.txt", "work")
    git(["push", "--quiet", "--set-upstream", "origin", "feature/pushed"], cwd=lane)

    status = backend.status(lane, "main")
    assert status.unpushed_count == 0, "nothing left to push"
    assert status.ahead_of_base == 1, "but the work is still not in the base branch"
    assert status.has_own_commits
