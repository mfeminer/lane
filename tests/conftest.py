"""Real temporary git repositories.

`GitBackend` is never faked, so the fixtures here build genuine repositories: a
bare "remote" plus a clone of it. Worktree creation, fetching and merge detection
are exercised for real.

Nothing here reaches the network or authenticates: the "remote" is a bare
repository on disk, which `git` treats like any other.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from lane.git.cli_backend import CliGitBackend

_IDENTITY = (
    ("user.email", "tests@example.invalid"),
    ("user.name", "lane tests"),
    ("commit.gpgsign", "false"),
    ("gc.auto", "0"),
)


def git(args: list[str], cwd: Path | None = None) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise AssertionError(f"fixture git {' '.join(args)} failed:\n{done.stderr}")
    return done.stdout


def _configure(repo: Path) -> None:
    for key, value in _IDENTITY:
        git(["config", key, value], cwd=repo)


@dataclass
class Origin:
    """A bare repository standing in for a remote, plus helpers to move it on."""

    path: Path
    default_branch: str

    def advance(self, message: str, *, branch: str | None = None) -> str:
        """Add a commit to the remote, so a clone can be behind it."""
        target = branch or self.default_branch
        scratch = self.path.parent / f"advance-{abs(hash(message)) % 10**8}"
        git(["clone", "--quiet", "--branch", target, str(self.path), str(scratch)])
        _configure(scratch)
        (scratch / f"{abs(hash(message)) % 10**8}.txt").write_text(f"{message}\n")
        git(["add", "-A"], cwd=scratch)
        git(["commit", "--quiet", "-m", message], cwd=scratch)
        git(["push", "--quiet", "origin", target], cwd=scratch)
        head = git(["rev-parse", "HEAD"], cwd=scratch).strip()
        _rmtree(scratch)
        return head

    def create_branch(self, name: str, at: str | None = None) -> None:
        git(["branch", name, at or self.default_branch], cwd=self.path)

    def delete_branch(self, name: str) -> None:
        git(["branch", "-D", name], cwd=self.path)

    def set_url_to(self, url: str, clone: Path) -> None:
        """Point a clone's origin somewhere else, to test non-GitHub remotes."""
        git(["remote", "set-url", "origin", url], cwd=clone)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def build_repo(
    root: Path,
    *,
    default_branch: str = "main",
    commits: int = 2,
) -> tuple[Origin, Path]:
    """Return (origin, clone). The clone has origin/HEAD set, as a real one does."""
    seed = root / "seed"
    origin_path = root / "origin.git"
    clone = root / "clone"

    git(["init", "--quiet", "--initial-branch", default_branch, str(seed)])
    _configure(seed)
    for index in range(commits):
        (seed / f"file{index}.txt").write_text(f"content {index}\n")
        git(["add", "-A"], cwd=seed)
        git(["commit", "--quiet", "-m", f"commit {index}"], cwd=seed)

    git(["clone", "--quiet", "--bare", str(seed), str(origin_path)])
    # A real remote advertises its HEAD; a bare clone of a local path may not.
    git(["symbolic-ref", "HEAD", f"refs/heads/{default_branch}"], cwd=origin_path)
    _rmtree(seed)

    git(["clone", "--quiet", str(origin_path), str(clone)])
    _configure(clone)
    return Origin(origin_path, default_branch), clone


@pytest.fixture
def backend() -> CliGitBackend:
    return CliGitBackend()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Origin, Path]:
    """A `main` repository: a bare remote and a clone."""
    return build_repo(tmp_path / "main-repo")


@pytest.fixture
def master_repo(tmp_path: Path) -> tuple[Origin, Path]:
    """A `master` repository, because the default branch is not always `main`."""
    return build_repo(tmp_path / "master-repo", default_branch="master")


@pytest.fixture
def dev_repo(tmp_path: Path) -> tuple[Origin, Path]:
    """A `dev` repository — what the maintainer's primary repository actually uses."""
    return build_repo(tmp_path / "dev-repo", default_branch="dev")


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    root = tmp_path / "Projects"
    root.mkdir()
    return root


@pytest.fixture
def lanes_root(tmp_path: Path) -> Path:
    return tmp_path / "Lanes"


@pytest.fixture
def xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect XDG config and state at a temporary directory.

    The filesystem runs for real; only where it points is redirected, so file modes
    and directory creation are genuinely exercised.
    """
    config = tmp_path / "xdg-config"
    state = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("LANE_PROJECTS_ROOT", "LANE_LANES_ROOT", "LANE_EDITOR"):
        monkeypatch.delenv(name, raising=False)
    yield tmp_path
