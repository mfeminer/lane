"""The branch prefixes offered when a lane names its branch, in a file of lane's own.

`${XDG_CONFIG_HOME:-~/.config}/lane/branch_prefixes.toml`, mode 0600 in the same 0700
directory as `config.toml` and `prepare.toml`.

**This is not the per-lane choice.** Which prefix a lane takes is still decided lane by
lane, at the prompt, exactly as AGENTS.md requires — one lane `bugfix/…` while the next
is `feature/…`. What is configurable is the *menu* those choices are made from, which a
team with its own conventions has always had to reach for `other…` to get at.

## Why not `config.toml`

The same reason `prepare.toml` is not in there, and it applies harder.
`ConfigStore.save()` rebuilds the file body from the three settings it knows about, so
**any key it does not know is dropped on write** — and the version stamp is compared on
every load, so a version bump rewrites the file. Beyond that, `config.py` is explicit
that three settings is a closed list, and an unbounded list of strings is not a fourth
setting in any case: it has no per-value default, no environment override and no
validation of its own.

A separate file can also be deleted to put the six back without touching the three
settings themselves.

## Why a seed rather than a written-out default

The file is absent for everybody who has never opened this screen, and an absent file
means the six lane has always offered. So nothing changes for them, and there is no
first-run write to get wrong. An **empty** list means the same thing: a menu with
nothing on it is not an answer anybody chose, and forgetting the last prefix is how
somebody would arrive at one.

## It never announces itself

No rewrite, no `.bak`, no upgrade notice — the invariant that the upgrade notice stays
one short line is not served by a third file also having something to say. An unreadable
file means the seed, never an exception and never a rewrite; the screen showing the six
again is itself the signal.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from pathlib import Path

import tomli_w

from lane.config import CONFIG_VERSION, config_home

DEFAULT_PREFIXES = ("feature", "bugfix", "hotfix", "chore", "refactor", "docs")
"""What lane has always offered, and what an untouched installation still offers."""

_DIR_MODE = 0o700
_FILE_MODE = 0o600


class BranchPrefixStore:
    """Reads and writes `branch_prefixes.toml`. Knows nothing about prompting."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory if directory is not None else config_home()

    @property
    def path(self) -> Path:
        return self._dir / "branch_prefixes.toml"

    # -- reading -------------------------------------------------------------
    def load(self) -> tuple[str, ...]:
        """The prefixes to offer — customised if there are any, the seed otherwise."""
        return _read(self.path) or DEFAULT_PREFIXES

    def customised(self) -> bool:
        """Whether `load()` is somebody's list or the seed.

        `load()` deliberately cannot say: it answers "what is offered", and the whole
        point of the seed is that offering it needs no file. This is the second question
        — and a caller reporting to a script needs it, because "these are the six because
        nobody has touched them" and "these are the six because somebody wrote them down"
        are different facts about the same six.
        """
        return bool(_read(self.path))

    # -- writing -------------------------------------------------------------
    def save(self, prefixes: Sequence[str]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dir.chmod(_DIR_MODE)
        body: dict[str, object] = {"version": CONFIG_VERSION}
        body["prefix"] = list(prefixes)
        self.path.write_text(tomli_w.dumps(body), encoding="utf-8")
        self.path.chmod(_FILE_MODE)


def _read(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    try:
        body = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError, ValueError:
        return ()
    raw = body.get("prefix")
    if not isinstance(raw, list):
        return ()
    return tuple(one.strip() for one in raw if isinstance(one, str) and one.strip())
