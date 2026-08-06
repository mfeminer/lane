"""Which copy of lane is running, and is it the one that was just installed?

Several copies of lane can sit on one machine (~/bin, a checkout, whatever is
first on PATH), so the version number alone cannot answer that. The fingerprint
can.

Under PyInstaller one-file, `__file__` points into a temporary extraction
directory that changes on every run — useless for this. `sys.executable` is the
installed binary, so that is what is reported and what is hashed.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from lane import __version__

APP = "lane"

_FINGERPRINT_LENGTH = 7
_UNKNOWN = "unknown"

# PEP 440's release segment — the `1.2.3` at the front of a version, before any
# `.postN` / `.devN` / `+local` that a build between tags carries.
_RELEASE_SEGMENT = re.compile(r"^\d+(?:\.\d+)*")


def release_of(version: str) -> str:
    """The release a build came from.

    The version is derived from `git describe`, so a build between tags carries
    a suffix that moves with every commit. The config stamp asks "which release
    is this" rather than "which build" because it is compared on every load:
    stamping the full version would rewrite the file, leaving a `.bak` beside
    it, on every run of a development checkout.
    """
    match = _RELEASE_SEGMENT.match(version)
    return match.group() if match else version


def release() -> str:
    """The release this copy of lane came from."""
    return release_of(__version__)


def executable_path() -> Path:
    """The file that is actually running — the binary when frozen."""
    return Path(sys.executable)


def build_id() -> str:
    """A short fingerprint of the running executable.

    Answers "did this file change", which is the question doctor exists to
    settle. Unreadable executables are not an error worth failing over: the
    fingerprint is diagnostic, not load-bearing.
    """
    try:
        digest = hashlib.sha256(executable_path().read_bytes()).hexdigest()
    except OSError:
        return _UNKNOWN
    return digest[:_FINGERPRINT_LENGTH]


def version_line() -> str:
    return f"{APP} {__version__} (build {build_id()})"
