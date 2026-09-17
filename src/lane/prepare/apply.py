"""Doing it: cloning, linking, running a command, and measuring a path.

The only place in lane that copies anything, links anything, or spawns a command the
user configured. It is **not a fifth seam** — the four are deliberate, and the
filesystem runs for real in tests, which is exactly what makes these paths testable
without one.

## Copy-on-write is a syscall, not a subprocess

`clonefile(2)` is not in the standard library, but it is reachable: `ctypes` is, and
the symbol resolves through the libSystem this process already links. That is worth
the twelve lines it costs, because of what the alternative does when cloning is
impossible:

| | Same volume, APFS | Across volumes |
|---|---|---|
| `clonefile(2)` | a whole tree in one call — 64 MB in 0.3 ms | fails `EXDEV`, having done nothing |
| `cp -Rc` | clones — 64 MB in 9 ms | **silently** copies for real (`cp(1)` documents it) |

Measured, not assumed. And the `cp -Rc` fallback is worse than slow: copying that
tree onto a volume too small for it ran for 258 ms, filled the volume, exited 1 and
left a partial file behind. The user configured `clone` expecting it to be free; the
least lane owes them is to know when it was not.

`CDLL(None)` rather than `find_library("System")` is what keeps this working inside a
PyInstaller one-file bundle.

## Everything is staged, then swapped

Every write goes to `<target>.lane-partial` and is renamed into place. This is not
tidiness: `clonefile` refuses an existing destination with `EEXIST`, so staging is how
overwriting works at all. The property it buys is the one that means preparation needs
no rollback logic and no deferred interrupt — **the target is the old thing or the new
thing, never half of one.**
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lane.environment import detached_child

_STAGED_SUFFIX = ".lane-partial"
_RUN_TIMEOUT = 1800
"""Half an hour. A dependency install is slow; it is not infinite, and a step that
hangs for ever would hang the lane behind it."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a step did, in the shape the reporting needs.

    `copied` distinguishes a real copy from a clone. It is not a detail: the user
    asked for something that should have been free, and a gigabyte of disk is not.
    """

    ok: bool
    detail: str = ""
    copied: bool = False


def staged_path(target: Path) -> Path:
    """Where a write goes before it is swapped into place."""
    return target.parent / f"{target.name}{_STAGED_SUFFIX}"


# -- copy-on-write ---------------------------------------------------------------


def _load_clonefile() -> Callable[[bytes, bytes, int], int] | None:
    """`clonefile(2)`, or None where there is no such call — which is anywhere but macOS.

    **The platform is checked before the library is opened, and that is not tidiness.**
    `CDLL(None)` — the form that keeps this working inside a PyInstaller one-file bundle
    — raises `TypeError` on Windows, because there is no "the process's own symbols" to
    ask for: `LoadLibrary` wants a name. That is neither of the errors caught below, and
    this runs at **import time**, so lane did not start at all on Windows. Asking only
    where the question has an answer is both the fix and the honest shape.
    """
    if sys.platform != "darwin":
        return None
    try:
        library = ctypes.CDLL(None, use_errno=True)
        entry = library.clonefile
    except OSError, AttributeError:  # pragma: no cover - a macOS without the symbol
        return None
    entry.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    entry.restype = ctypes.c_int

    def call(source: bytes, target: bytes, flags: int) -> int:
        return int(entry(source, target, flags))

    return call


_CLONEFILE = _load_clonefile()

_Cloner = Callable[[bytes, bytes, int], int]
_Swapper = Callable[[Path, Path], None]


def _device_of(path: Path) -> int:
    return path.stat().st_dev


def cloning_available(
    source_root: Path,
    target_root: Path,
    *,
    _device: Callable[[Path], int] = _device_of,
) -> bool:
    """Whether a clone between these two directories can actually be a clone.

    Asked in the cheapest order. Two `stat` calls settle it when the answer is no:
    different volumes cannot clone, ever, whatever the filesystem is. Only when they are
    on one volume is a probe needed, and that probe runs **entirely inside the target** —
    never writing into the projects root, a directory lane reads and has never written to.

    A path that does not exist yet is answered by its nearest existing ancestor, which is
    on the volume it will be created on. The lanes folder is routinely absent until the
    first lane is opened, and "I cannot tell you" would be a worse answer than the true
    one.
    """
    if _CLONEFILE is None:  # pragma: no cover - platform dependent
        return False
    source, target = _nearest_existing(source_root), _nearest_existing(target_root)
    try:
        if _device(source) != _device(target):
            return False
    except OSError:
        return False
    return _probe(target)


def _nearest_existing(path: Path) -> Path:
    """`path` itself, or the closest ancestor that is there. `/` always is."""
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return path  # pragma: no cover - unreachable while the root exists


def _probe(directory: Path) -> bool:
    """Clone a scratch file beside itself, and clear up either way."""
    source = directory / f"probe{_STAGED_SUFFIX}"
    target = directory / f"probe{_STAGED_SUFFIX}-clone"
    try:
        source.write_bytes(b"lane")
        _unlink(target)
        assert _CLONEFILE is not None
        return _CLONEFILE(os.fsencode(source), os.fsencode(target), 0) == 0
    except OSError:
        return False
    finally:
        _unlink(source)
        _unlink(target)


def clone(
    source: Path,
    target: Path,
    *,
    _clone_file: _Cloner | None = _CLONEFILE,
    _swap: _Swapper | None = None,
) -> Outcome:
    """Copy-on-write where it can be, a real copy where it cannot — and say which.

    The underscored parameters exist for the tests that have to see both halves of
    that sentence, and for the one that has to see a swap fail without arranging a
    full disk.
    """
    if not _exists(source):
        return Outcome(ok=False, detail=f"{source} is not there any more")

    staged = staged_path(target)
    copied = False
    try:
        _remove(staged)
        target.parent.mkdir(parents=True, exist_ok=True)
        cloned = _clone_file is not None and (
            _clone_file(os.fsencode(source), os.fsencode(staged), 0) == 0
        )
        if cloned:
            copied = False
        else:
            _copy(source, staged)
            copied = True
        (_swap or _replace)(staged, target)
    except OSError as exc:
        _remove(staged)
        return Outcome(ok=False, detail=_reason(exc), copied=copied)
    return Outcome(ok=True, copied=copied)


def _copy(source: Path, staged: Path) -> None:
    """The fallback: real bytes, real disk. `shutil`, so still no subprocess."""
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, staged, symlinks=True)
    else:
        shutil.copy2(source, staged, follow_symlinks=False)


# -- linking ---------------------------------------------------------------------


# -- running ---------------------------------------------------------------------


def run(command: str, directory: Path) -> Outcome:
    """Run a configured command, wait for it, and report what it said if it failed.

    `shlex.split` rather than a shell: the command comes from lane's own
    configuration, and handing it to a shell would make quoting part of the interface
    for no gain. A command that genuinely wants a shell writes `sh -c '…'`, which
    reads as the deliberate thing it is.

    Detached for the reason the git backend is: the terminal's Ctrl-C reaches lane and
    nothing else, so lane decides what happens to the child instead of the terminal
    killing it out from under a spinner. lane still owns its lifetime — an interrupt
    unwinds `subprocess.run`, which kills it on the way out. `lane.environment` owns
    how each platform spells that, because they do not spell it the same.
    """
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return Outcome(ok=False, detail=f"{command} could not be read: {exc}")
    if not parts:
        return Outcome(ok=False, detail="there is no command to run")

    try:
        done = subprocess.run(
            parts,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT,
            check=False,
            **detached_child(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Outcome(ok=False, detail=f"{command} could not run: {_reason(exc)}")

    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        tail = said[-1] if said else "no output"
        return Outcome(ok=False, detail=f"{command} exited {done.returncode}: {tail}")
    return Outcome(ok=True, detail=(done.stdout or "").strip())


# -- measuring -------------------------------------------------------------------


def measure(path: Path) -> int | None:
    """How much this path holds, in bytes, or None when there is nothing there.

    `os.scandir` rather than `du -sk` in a subprocess. `du` was the faster loop and it
    was also a Unix binary: on Windows it is simply absent, and `measure` was written to
    answer None when the command cannot be found — so every size on the screen would
    have read `—`, silently removing the one thing standing between a user and cloning
    twenty gigabytes by accident. A walk in Python is the same code on all three
    platforms and removes a spawn rather than adding a branch.

    The speed argument the subprocess was written for did not survive being measured
    again: on a real `node_modules` of 77,868 entries, `du -sk` takes 0.27-0.30 s warm
    and this walk takes 0.31 s. Both belong on the table's `fill` thread, which is where
    this has always been called from, and neither is close to blocking a paint.

    **Apparent size, not disk blocks.** `du` answered in allocated blocks, rounded up
    per file and de-duplicated by inode; this sums `st_size`. The same tree reads
    990 MB to `du` and 783 MB here — the difference is per-file rounding across 78k
    small files, and the bytes are the honest answer to what the screen actually asks:
    how much is about to be copied in. They are also the same number on every
    filesystem, which the block count never was.

    **A symlink holds nothing**, and is never followed. A linked `node_modules` points
    into the main clone: following it would report the main clone's size as the lane's,
    and counting the link itself would put a hundred-odd bytes of target path into a
    number that is supposed to mean "this much is about to be copied in". Nothing is,
    so it is zero.
    """
    if not _exists(path):
        return None
    if path.is_symlink():
        return 0
    if not path.is_dir():
        try:
            return path.lstat().st_size
        except OSError:
            return None
    return _tree_size(path)


def _tree_size(directory: Path) -> int:
    """Sum every file under `directory`, reporting what it could reach.

    An unreadable subdirectory is skipped rather than failing the whole measurement: a
    short number is more use than no number, and `—` on a path the user is deciding
    about is the answer this function exists to avoid.
    """
    total = 0
    stack = [directory]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


_UNITS = ("B", "KB", "MB", "GB", "TB")


def size_phrase(size: int | None) -> str:
    """`1.2 GB`, `340 MB`, `—` when it is not known.

    Decimal units, because that is what a package manager and a disk both report, and
    one decimal place, because the second one never changed a decision.
    """
    if size is None:
        return "—"
    scaled = float(size)
    for unit in _UNITS:
        if scaled < 1000 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(scaled)} {unit}"
            return f"{scaled:.1f} {unit}".replace(".0 ", " ")
        scaled /= 1000
    raise AssertionError("unreachable")  # pragma: no cover


# -- filesystem odds and ends ----------------------------------------------------


def _exists(path: Path) -> bool:
    """Whether anything is there — a broken symlink included, since it is *there*."""
    return path.exists() or path.is_symlink()


def _unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _remove(path: Path) -> None:
    """Delete whatever is at `path`, never following a symlink out of the lane.

    A linked `node_modules` points into the main clone. Removing the link must remove
    the link; anything that followed it would delete the thing every other lane is
    sharing.
    """
    if path.is_symlink() or path.is_file():
        _unlink(path)
        return
    shutil.rmtree(path, ignore_errors=True)


def _replace(staged: Path, target: Path) -> None:
    """Swap the staged path in, leaving the target whole at every moment.

    `os.replace` is atomic for a file and for a symlink, but not for a non-empty
    directory (`ENOTEMPTY`), so the old directory is moved aside first and removed
    afterwards. The window that leaves is one where the target is *absent* — which the
    next enter repairs — never one where it is half-populated.
    """
    if not _exists(target):
        staged.replace(target)
        return
    if target.is_symlink() or target.is_file():
        _unlink(target)
        staged.replace(target)
        return
    aside = target.parent / f"{target.name}{_STAGED_SUFFIX}-old"
    _remove(aside)
    target.replace(aside)
    try:
        staged.replace(target)
    finally:
        _remove(aside)


def _reason(exc: BaseException) -> str:
    """The message a user can act on, without the Python punctuation around it."""
    text = getattr(exc, "strerror", None) or str(exc)
    return str(text)
