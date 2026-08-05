"""Finding projects, and explaining it when there are none.

A project is a direct subdirectory of `projects_root` that is a git repository:
`<root>/<project>/.git`. The root itself is not a repository — it is the folder the
projects sit in.

The diagnostics matter more than the discovery. The usual cause of an empty list is
a projects root pointing one level too high or too low, and saying "no projects
found" leaves the user to guess which. So lane says how many subfolders it looked
at, and when the repositories turn out to be nested it points at the folder that
should be used instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lane.git.backend import GitBackend


@dataclass(frozen=True, slots=True)
class Project:
    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class NoProjects:
    """Why the list is empty, in enough detail to act on."""

    root: Path
    root_exists: bool
    subdirectory_count: int
    nested_example: Path | None
    """A repository found deeper than one level, e.g. <root>/<org>/<repo>."""

    @property
    def suggested_root(self) -> Path | None:
        """The folder the user probably meant."""
        if self.nested_example is None:
            return None
        return self.nested_example.parent


def list_projects(root: Path | None, backend: GitBackend) -> list[Project]:
    """Every direct subdirectory of `root` that is a git repository, sorted."""
    if root is None or not root.is_dir():
        return []
    found: list[Project] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        # A `.git` entry may be a directory or, in a worktree, a file.
        if not (child / ".git").exists():
            continue
        if backend.is_repository(child):
            found.append(Project(name=child.name, path=child))
    return found


def count_subdirectories(root: Path) -> int:
    """How many subfolders were examined — used to explain a rejection."""
    if not root.is_dir():
        return 0
    try:
        return sum(1 for child in root.iterdir() if child.is_dir())
    except OSError:
        return 0


def find_nested_repository(root: Path, backend: GitBackend) -> Path | None:
    """Look for `<root>/<org>/<repo>`, the common misconfiguration.

    Uses `backend.is_repository` rather than merely checking for a `.git` entry, so
    that this agrees with `list_projects`. When the two disagreed, lane could report
    "no projects here" and then suggest a folder that has none either — advice that
    contradicted what it had just said.

    Bounded to one extra level rather than a full walk: a projects root can be very
    large, and this runs while the user is waiting.
    """
    if not root.is_dir():
        return None
    try:
        for depth_one in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not depth_one.is_dir():
                continue
            for depth_two in sorted(depth_one.iterdir(), key=lambda p: p.name.lower()):
                if not depth_two.is_dir() or not (depth_two / ".git").exists():
                    continue
                # The cheap check passed; now ask git, as the listing does.
                if backend.is_repository(depth_two):
                    return depth_two
    except OSError:
        return None
    return None


def diagnose(root: Path | None, backend: GitBackend) -> NoProjects:
    """Everything worth saying about a projects root that yielded nothing."""
    if root is None:
        return NoProjects(
            root=Path(),
            root_exists=False,
            subdirectory_count=0,
            nested_example=None,
        )
    return NoProjects(
        root=root,
        root_exists=root.is_dir(),
        subdirectory_count=count_subdirectories(root),
        nested_example=find_nested_repository(root, backend),
    )
