"""The git backend: subprocess against the `git` CLI. The only place `git` is spawned.

ADR 0001 has the reasoning. The two rules that keep this honest:

1. **Parse only machine-oriented output** — `--porcelain`, `rev-list --count`,
   `show-ref --verify --quiet`, `--abbrev-ref`, `merge-base --is-ancestor` (exit
   code only). Never human-readable output, never localised output.
2. **Pin the environment**, so a user's git config, locale or aliases cannot change
   what is read back.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from lane.git.backend import FetchResult, GitError, WorktreeStatus

_TIMEOUT = 120
_FETCH_TIMEOUT = 300

# Config forced on every invocation, so what comes back is what the code expects
# rather than what the user has configured.
_FORCED_CONFIG = (
    "core.quotePath=false",  # UTF-8 paths readable, not \303\274 escapes
    "color.ui=false",
    "core.pager=cat",
    "advice.detachedHead=false",
)


def _same_directory(left: Path, right: Path) -> bool:
    """Whether two paths are the same directory on disk.

    Not a string comparison, deliberately. macOS and Windows filesystems are
    case-insensitive, so a user who types `/users/me/projects` reaches the same
    directory as `/Users/me/Projects` — but `Path.resolve()` keeps whichever case
    was typed, while `git rev-parse --show-toplevel` reports the case on disk.
    Comparing those two as strings made every project silently vanish.

    `samefile` asks the filesystem (device and inode), which is immune to case,
    trailing separators, `.` segments and symlinks alike.
    """
    try:
        return left.samefile(right)
    except OSError:
        # One of them stopped existing between the check and here.
        return False


class CliGitBackend:
    """Drives `git`. Nothing above this module knows that is how it works."""

    def __init__(self, git_command: str = "git") -> None:
        self._git = git_command

    # -- plumbing ------------------------------------------------------------
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Deterministic, locale-independent output.
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        # Never let git open an editor or a credential prompt of its own.
        env["GIT_EDITOR"] = "true"
        env["GIT_TERMINAL_PROMPT"] = "0"
        # Ignore system/global config that could redirect what we read.
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        return env

    def _run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: int = _TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        command = [self._git]
        for setting in _FORCED_CONFIG:
            command += ["-c", setting]
        if cwd is not None:
            command += ["-C", str(cwd)]
        command += args
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env(),
                check=False,
                # Out of lane's process group, so the terminal's Ctrl-C reaches lane
                # and nothing else. Otherwise a removal in flight is killed half-way
                # whatever lane decides to do with its own copy of the signal, and
                # deferring it (`lane.interrupts`) would buy nothing. lane still owns
                # the child's lifetime: an interrupt lane does not defer unwinds
                # `subprocess.run`, which kills it on the way out.
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise GitError(f"git is not installed: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git timed out after {timeout}s: {' '.join(args)}") from exc

    def _out(self, args: list[str], *, cwd: Path | None = None) -> str:
        """Run and require success."""
        done = self._run(args, cwd=cwd)
        if done.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}",
                stderr=done.stderr,
            )
        return done.stdout

    def _quiet(self, args: list[str], *, cwd: Path | None = None) -> bool:
        """Run for the exit code alone."""
        return self._run(args, cwd=cwd).returncode == 0

    def _line(self, args: list[str], *, cwd: Path | None = None) -> str | None:
        """First line of output, or None when the command failed or said nothing."""
        done = self._run(args, cwd=cwd)
        if done.returncode != 0:
            return None
        text = done.stdout.strip()
        return text.splitlines()[0] if text else None

    # -- interrogation -------------------------------------------------------
    def is_repository(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        # --is-inside-work-tree would say yes for a subdirectory; we want this path
        # to *be* the repository root, so compare it with what git reports.
        top = self._line(["rev-parse", "--show-toplevel"], cwd=path)
        if top is None:
            return False
        return _same_directory(Path(top), path)

    def version(self) -> str | None:
        return self._line(["--version"])

    def remote_url(self, path: Path, remote: str = "origin") -> str | None:
        return self._line(["remote", "get-url", remote], cwd=path)

    def default_branch(self, repo: Path) -> str | None:
        """`set-head --auto`, then origin/HEAD, then convention — never a guess.

        The refresh has to come *before* the read, not after: `refs/remotes/origin/HEAD`
        is written once at clone time and never follows the remote on its own, so a
        repository cloned back when the default was `master` would keep reporting
        `master` forever if the stale ref were trusted first. `set-head --auto` asks
        the remote and is what corrects it.

        Convention is a genuine last resort, reached only when the remote could not
        be asked (offline) and there was no origin/HEAD to fall back on either. When
        even that fails, None is returned so the caller can say it could not
        determine the branch: basing a lane on the wrong branch silently is worse
        than refusing.
        """
        # Needs the network, so it may well fail offline — in which case whatever
        # origin/HEAD already has on disk is the best available answer.
        self._run(["remote", "set-head", "origin", "--auto"], cwd=repo)
        found = self._origin_head(repo)
        if found is not None:
            return found

        for candidate in ("main", "master", "develop"):
            if self.rev_parse_verify(repo, f"origin/{candidate}"):
                return candidate

        return None

    def _origin_head(self, repo: Path) -> str | None:
        line = self._line(
            ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo,
        )
        if line is None:
            return None
        return line.removeprefix("origin/") or None

    def rev_parse_verify(self, repo: Path, rev: str) -> bool:
        return self._quiet(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], cwd=repo)

    def check_ref_format(self, branch: str) -> bool:
        if not branch:
            return False
        return self._quiet(["check-ref-format", "--branch", branch])

    def branch_merged(self, repo: Path, branch: str, base: str) -> bool:
        """Whether every commit on `branch` is already in `origin/<base>`.

        `git branch -d` applies this rule itself at deletion time, which is after the
        user has agreed to the deletion. Asking beforehand is what lets the summary
        name the branches that hold something while there is still a choice.
        """
        return self._quiet(
            ["merge-base", "--is-ancestor", branch, f"origin/{base}"],
            cwd=repo,
        )

    def branch_exists(self, repo: Path, branch: str) -> bool:
        return self._quiet(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo,
        )

    # -- fetching ------------------------------------------------------------
    def fetch_prune(self, repo: Path, remote: str = "origin") -> FetchResult:
        """Being offline is not fatal — it only makes merge state stale."""
        try:
            done = self._run(
                ["fetch", "--prune", "--quiet", remote],
                cwd=repo,
                timeout=_FETCH_TIMEOUT,
            )
        except GitError as exc:
            return FetchResult(ok=False, detail=str(exc))
        if done.returncode != 0:
            return FetchResult(
                ok=False,
                detail=done.stderr.strip().splitlines()[-1:][0]
                if done.stderr.strip()
                else "fetch failed",
            )
        return FetchResult(ok=True)

    # -- status --------------------------------------------------------------
    def status(self, worktree: Path, base: str, start: str = "") -> WorktreeStatus:
        branch = self._line(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree)
        detached = branch is None or branch == "HEAD"
        head_short = self._line(["rev-parse", "--short", "HEAD"], cwd=worktree) or "unknown"

        porcelain = self._run(["status", "--porcelain", "--untracked-files=normal"], cwd=worktree)
        dirty_count = len([line for line in porcelain.stdout.splitlines() if line.strip()])

        upstream = self._line(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=worktree
        )

        # Not the same question as `upstream`, which stops resolving the moment
        # `origin/<branch>` is pruned — which is what merging a pull request with
        # "delete branch" does to every lane that landed.
        pushed_before = not detached and self._quiet(
            ["config", "--get", f"branch.{branch}.remote"], cwd=worktree
        )

        # Against the upstream when there is one, otherwise against origin/<base>:
        # a lane branch has no upstream until it is first pushed.
        compare_to = upstream if upstream is not None else f"origin/{base}"
        unpushed = self._count_commits(worktree, f"{compare_to}..HEAD")

        # Against the base specifically, never the upstream: pushing a branch does
        # not put its commits into the base branch.
        ahead_of_base = self._count_commits(worktree, f"origin/{base}..HEAD")

        merged = self._quiet(
            ["merge-base", "--is-ancestor", "HEAD", f"origin/{base}"], cwd=worktree
        )

        # From the lane's own starting point when it is known. Falling back to
        # ahead_of_base is weaker but never worse than having no signal at all.
        own = (
            self._count_commits(worktree, f"{start}..HEAD")
            if start and self.rev_parse_verify(worktree, start)
            else ahead_of_base
        )

        return WorktreeStatus(
            branch=None if detached else branch,
            head_short=head_short,
            dirty_count=dirty_count,
            upstream=upstream,
            pushed_before=pushed_before,
            unpushed_count=unpushed,
            ahead_of_base=ahead_of_base,
            own_commits=own,
            merged=merged,
        )

    _MOVED = re.compile(r"^checkout: moving from (?P<from>.+) to (?P<to>.+)$")

    def branches_used(self, worktree: Path) -> list[str]:
        """Every branch this worktree has had checked out, most recently first.

        Read from the worktree's own HEAD reflog, which is the only record of it:
        lane is absent while the work happens, so a branch created mid-task appears
        nowhere in its metadata. Both sides of each entry are taken — the branch the
        worktree was created on shows up only as somewhere it moved *from*.

        Names are filtered back through git: reflog entries outlive the branches they
        name, and a spell on a detached HEAD leaves a bare commit id behind.
        """
        done = self._run(["reflog", "show", "HEAD", "--format=%gs"], cwd=worktree)
        if done.returncode != 0:
            return []

        seen: dict[str, None] = {}
        for line in done.stdout.splitlines():
            moved = self._MOVED.match(line.strip())
            if moved is None:
                continue
            # `to` before `from`: within one entry the destination is the more recent.
            for name in (moved["to"], moved["from"]):
                if name not in seen and self.branch_exists(worktree, name):
                    seen[name] = None
        return list(seen)

    def commits_since(self, worktree: Path, commit: str) -> int | None:
        """How many commits HEAD has that `commit` does not — or None if it is not here.

        `^{commit}` is what makes the question real: a full-length hex string verifies
        as a *revision* whether or not the object exists, so without it an amended or
        rebased branch would answer 0 — "nothing added since it merged" — about a
        commit this repository has never seen.
        """
        if not commit or not self.rev_parse_verify(worktree, f"{commit}^{{commit}}"):
            return None
        return self._count_commits(worktree, f"{commit}..HEAD")

    def _count_commits(self, worktree: Path, rev_range: str) -> int:
        line = self._line(["rev-list", "--count", rev_range], cwd=worktree)
        if line is None:
            return 0
        try:
            return int(line)
        except ValueError:
            return 0

    def dirty_files(self, worktree: Path, limit: int = 20) -> list[str]:
        done = self._run(["status", "--porcelain", "--untracked-files=normal"], cwd=worktree)
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        return lines[:limit]

    def log_oneline(self, worktree: Path, rev_range: str, limit: int = 10) -> list[str]:
        done = self._run(
            ["log", "--oneline", "--no-decorate", f"--max-count={limit}", rev_range],
            cwd=worktree,
        )
        if done.returncode != 0:
            return []
        return [line for line in done.stdout.splitlines() if line.strip()]

    # -- the worktree lifecycle ----------------------------------------------
    def add_worktree_new_branch(
        self, repo: Path, path: Path, branch: str, start_point: str
    ) -> None:
        """`--no-track` is the invariant: no upstream, so a bare push cannot reach base."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._out(
            ["worktree", "add", "--no-track", "-b", branch, str(path), start_point],
            cwd=repo,
        )

    def add_worktree_existing_branch(self, repo: Path, path: Path, branch: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._out(["worktree", "add", str(path), branch], cwd=repo)

    def add_worktree_detached(self, repo: Path, path: Path, start_point: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._out(["worktree", "add", "--detach", str(path), start_point], cwd=repo)

    def remove_worktree(self, repo: Path, path: Path, *, force: bool = False) -> None:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        self._out(args, cwd=repo)

    def prune_worktrees(self, repo: Path) -> None:
        self._run(["worktree", "prune"], cwd=repo)

    # -- branches ------------------------------------------------------------
    def create_branch(self, repo: Path, branch: str, at: str) -> None:
        self._out(["branch", branch, at], cwd=repo)

    def delete_branch(self, repo: Path, branch: str, *, force: bool = False) -> bool:
        """`-d` unless forced, so git applies the merged check itself."""
        flag = "-D" if force else "-d"
        return self._quiet(["branch", flag, branch], cwd=repo)

    def head_commit(self, worktree: Path) -> str:
        return self._out(["rev-parse", "HEAD"], cwd=worktree).strip()
