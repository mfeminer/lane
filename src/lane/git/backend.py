"""The `GitBackend` seam.

**Never faked.** Tests use the real implementation against temporary repositories,
because worktree creation, fetching and merge detection are exactly the things a
fake would get wrong in the same way the code does. This seam exists so the
implementation can be *swapped*, not so tests can avoid git.

ADR 0001 decided that implementation is subprocess against the `git` CLI. If
libgit2 ever grows worktree removal and a detached-worktree option, that can be
swapped in here without the rest of the application noticing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class GitError(Exception):
    """A git command failed in a way the caller must deal with."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Fetching is allowed to fail — being offline is not an error worth stopping for.

    It does mean merge state is stale, and the caller says so.
    """

    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class WorktreeStatus:
    """Everything the listing and the close checks need about one lane.

    Collected in one place so it can be gathered concurrently, one lane per thread.
    """

    branch: str | None
    """None when HEAD is detached."""

    head_short: str
    dirty_count: int
    upstream: str | None
    pushed_before: bool
    """Whether this branch was ever pushed, even if its remote branch is now gone.

    A missing `upstream` has two causes that look identical and mean opposite things:
    a branch that was never pushed, and a branch whose remote was deleted when its
    pull request merged. `branch.<name>.remote` survives the prune, so it is what
    keeps lane from announcing "never pushed" about work that plainly was.
    """

    unpushed_count: int
    """Commits not yet on the remote — against the upstream if there is one.

    With no upstream there is nothing to measure "on the remote" against, so this
    falls back to counting against `origin/<base>` and carries no push information at
    all. Read it with `pushed_before`, never alone.
    """

    ahead_of_base: int
    """Commits on HEAD that are not in `origin/<base>`.

    Distinct from `unpushed_count`: pushing a branch does not put its commits into
    the base branch.
    """

    own_commits: int
    """How many commits this lane has made since it was created.

    Counted from the lane's recorded starting commit, because nothing else can tell
    the two zero-cases apart: a lane opened a minute ago and a lane whose work has
    landed both have nothing ahead of `origin/<base>`. Falls back to
    `ahead_of_base` for lanes created before the starting commit was recorded.
    """

    merged: bool
    """Whether HEAD is an ancestor of `origin/<base>`.

    True for a fresh lane too, which is why callers that mean "the work landed"
    must also check `has_own_commits`.
    """

    @property
    def detached(self) -> bool:
        return self.branch is None

    @property
    def has_own_commits(self) -> bool:
        return self.own_commits > 0

    @property
    def landed(self) -> bool:
        """The lane did some work and that work is now in the base branch."""
        return self.merged and self.has_own_commits

    @property
    def label(self) -> str:
        """What to show in a listing."""
        return self.branch if self.branch is not None else f"(detached {self.head_short})"


class GitBackend(Protocol):
    # -- interrogation -------------------------------------------------------
    def is_repository(self, path: Path) -> bool: ...

    def version(self) -> str | None: ...

    def remote_url(self, path: Path, remote: str = "origin") -> str | None: ...

    def default_branch(self, repo: Path) -> str | None:
        """The remote's default branch, or None when it cannot be determined.

        Deliberately does not guess `main`: a wrong answer here silently bases a
        lane on the wrong branch. See ADR 0001 — this machine's primary repository
        uses `dev`.
        """
        ...

    def rev_parse_verify(self, repo: Path, rev: str) -> bool:
        """Whether `rev` resolves, for checking `origin/<base>` exists locally."""
        ...

    def check_ref_format(self, branch: str) -> bool:
        """Whether git will accept `branch` as a branch name. git owns this judgement."""
        ...

    def branch_exists(self, repo: Path, branch: str) -> bool: ...

    def branch_merged(self, repo: Path, branch: str, base: str) -> bool:
        """Whether every commit on `branch` is already in `origin/<base>`.

        The same question `WorktreeStatus.merged` answers about HEAD, asked by name —
        so a close can say which of a lane's branches hold unique work before it asks
        for permission to delete them.
        """
        ...

    # -- fetching ------------------------------------------------------------
    def fetch_prune(self, repo: Path, remote: str = "origin") -> FetchResult: ...

    # -- status --------------------------------------------------------------
    def status(self, worktree: Path, base: str, start: str = "") -> WorktreeStatus: ...

    def dirty_files(self, worktree: Path, limit: int = 20) -> list[str]:
        """Porcelain status lines, for showing what is uncommitted."""
        ...

    def log_oneline(self, worktree: Path, rev_range: str, limit: int = 10) -> list[str]: ...

    def branches_used(self, worktree: Path) -> list[str]:
        """Every branch this worktree has had checked out, most recently first.

        A lane's branches go with the lane, and there can be more than one of them:
        the work happens while lane is not watching, so a branch created mid-task is
        recorded nowhere except the worktree's own reflog. Only names that are still
        branches are returned.
        """
        ...

    # -- what a fresh checkout is missing ------------------------------------
    def ignored_paths(self, repo: Path) -> list[str]:
        """Everything git ignores in this repository and that exists on disk.

        One row per fully ignored directory rather than one per file inside it: a
        dependency tree is one decision, not two hundred thousand of them. Rows are
        relative to the repository root and never nested inside one another.
        """
        ...

    def ignored_as_given(self, worktree: Path, paths: Sequence[str]) -> set[str]:
        """Which of `paths` git ignores, taken exactly as spelled.

        The spelling is the question. A trailing slash asks about a *directory*; its
        absence asks about anything else — and `node_modules/` matches directories
        only, so a symlink of that name is an untracked file rather than an ignored
        one. That is the difference between `link` being usable for a path and not.

        A tracked path is never returned, which is what keeps lane from writing over
        one. Asked in a single call for the whole list.
        """
        ...

    def commits_since(self, worktree: Path, commit: str) -> int | None:
        """Commits on HEAD that `commit` does not have, or None when it is not here.

        None is the honest answer for a branch amended or rebased after its pull
        request merged: the commit that landed is no longer on it, so how much was
        added afterwards cannot be known from here. Never conflate that with zero.
        """
        ...

    # -- the worktree lifecycle ----------------------------------------------
    def add_worktree_new_branch(
        self, repo: Path, path: Path, branch: str, start_point: str
    ) -> None:
        """Create a worktree on a new branch with **no upstream**.

        The missing upstream is an invariant, not a detail: it is what stops a bare
        `git push` inside a lane from landing on the default branch.
        """
        ...

    def add_worktree_existing_branch(self, repo: Path, path: Path, branch: str) -> None: ...

    def add_worktree_detached(self, repo: Path, path: Path, start_point: str) -> None: ...

    def remove_worktree(self, repo: Path, path: Path, *, force: bool = False) -> None:
        """Remove a worktree.

        Without `force`, git refuses when the tree is dirty — that refusal is the
        safety net lane inherits by shelling out, so it is never bypassed except
        where the user has just been asked.
        """
        ...

    def prune_worktrees(self, repo: Path) -> None: ...

    # -- branches ------------------------------------------------------------
    def create_branch(self, repo: Path, branch: str, at: str) -> None:
        """Used to park `wip/<lane>` before a detached lane is removed."""
        ...

    def delete_branch(self, repo: Path, branch: str, *, force: bool = False) -> bool:
        """Delete a branch. Without `force` this is `-d`, so git applies the merged
        check itself. Returns False when git refused.
        """
        ...

    def head_commit(self, worktree: Path) -> str: ...
