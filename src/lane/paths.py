"""Path identity, in one place.

**Asked of the filesystem, never compared as strings** — that is an invariant, and
it earns a module of its own because it has two call sites that would otherwise
each carry a copy: the backend, which compares what git reports against what the
user configured, and `open`'s branch list, which matches a worktree path to a lane.
A second copy of this would be a second place for the invariant to be got wrong.
"""

from __future__ import annotations

from pathlib import Path


def same_directory(left: Path, right: Path) -> bool:
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
        # One of them stopped existing between the check and here — or never did,
        # which is what a stale `git worktree list` entry looks like.
        return False
