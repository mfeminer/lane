"""The `Environment` seam: the terminal, PATH, and launching the editor.

Faked in tests, which is what lets the suite run under pytest without a TTY and
without opening an editor. Note what this seam does *not* do: it reports which
tools are present **for doctor's benefit**, and it never decides whether an action
may proceed. Closing a lane decides from `GitHubClient`'s answer alone.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EditorLaunch:
    """What happened when we tried to open the editor."""

    launched: bool
    detail: str


class Environment(Protocol):
    def is_interactive(self) -> bool:
        """True when both stdin and stdout are terminals."""
        ...

    def which(self, tool: str) -> str | None:
        """The resolved path of `tool`, or None when it is not on PATH."""
        ...

    def tool_version(self, tool: str, *args: str) -> str | None:
        """A tool's version line, for doctor. None when it cannot be asked."""
        ...

    def launch_editor(self, command: str, path: Path) -> EditorLaunch: ...

    def directory_exists(self, path: Path) -> bool:
        """Used to spot an editor installed as a macOS .app but not on PATH."""
        ...


class RealEnvironment:
    """The one that touches the machine."""

    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def which(self, tool: str) -> str | None:
        if not tool:
            return None
        return shutil.which(tool)

    def tool_version(self, tool: str, *args: str) -> str | None:
        if self.which(tool) is None:
            return None
        try:
            done = subprocess.run(
                [tool, *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError, subprocess.SubprocessError:
            return None
        if done.returncode != 0:
            return None
        first = (done.stdout or done.stderr).strip().splitlines()
        return first[0] if first else None

    def launch_editor(self, command: str, path: Path) -> EditorLaunch:
        resolved = self.which(command)
        if resolved is not None:
            try:
                subprocess.Popen(
                    [resolved, str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                return EditorLaunch(launched=False, detail=f"{command} could not start: {exc}")
            return EditorLaunch(launched=True, detail=f"Launching {command} in the lane.")

        # A macOS editor installed as an .app but without its shell command.
        app = _MAC_APPS.get(command)
        if app is not None and self.directory_exists(Path(f"/Applications/{app}.app")):
            try:
                subprocess.Popen(
                    ["/usr/bin/open", "-a", app, str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                return EditorLaunch(launched=False, detail=f"{app} could not start: {exc}")
            return EditorLaunch(launched=True, detail=f"Launching {app} in the lane.")

        return EditorLaunch(launched=False, detail=f"'{command}' is not on your PATH")

    def directory_exists(self, path: Path) -> bool:
        return path.is_dir()


# Editors that commonly exist as an .app while their shell command is not installed.
_MAC_APPS = {
    "cursor": "Cursor",
    "code": "Visual Studio Code",
    "zed": "Zed",
    "subl": "Sublime Text",
}
