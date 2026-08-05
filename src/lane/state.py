"""Convenience state — what lane remembers to save you a keystroke.

Separate from configuration on purpose. The last project you opened a lane in is
not a *setting*: you never chose it, and losing it costs you nothing. So it lives
in `${XDG_STATE_HOME:-~/.local/state}/lane/state.toml` and lane works correctly
when that file is missing, unreadable or nonsense.

Because it is disposable, adding to it is not a new configuration key and does not
need asking. Adding to `config.py` does.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from lane.config import state_home

_FILE_MODE = 0o600
_DIR_MODE = 0o700


@dataclass(frozen=True, slots=True)
class State:
    last_project: str | None = None


class StateStore:
    """Best-effort persistence. Every operation is allowed to quietly do nothing."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory if directory is not None else state_home()

    @property
    def path(self) -> Path:
        return self._dir / "state.toml"

    def load(self) -> State:
        """A missing or corrupt file is simply an empty state."""
        try:
            body = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except OSError, tomllib.TOMLDecodeError, ValueError:
            return State()
        last = body.get("last_project")
        return State(last_project=last if isinstance(last, str) and last else None)

    def save(self, state: State) -> None:
        """Failure here must never interrupt what the user was doing."""
        body: dict[str, object] = {}
        if state.last_project:
            body["last_project"] = state.last_project
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._dir.chmod(_DIR_MODE)
            self.path.write_text(tomli_w.dumps(body), encoding="utf-8")
            self.path.chmod(_FILE_MODE)
        except OSError:
            return

    def remember_project(self, project: str) -> None:
        self.save(State(last_project=project))
