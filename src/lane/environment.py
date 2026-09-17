"""The `Environment` seam: the terminal, PATH, and launching the editor.

Faked in tests, which is what lets the suite run under pytest without a TTY and
without opening an editor. Note what this seam does *not* do: it reports which
tools are present **for doctor's benefit**, and it never decides whether an action
may proceed. Closing a lane decides from `GitHubClient`'s answer alone.

**This module is also where "how does this operating system say it" lives**, and
`detached_child` is the first thing in it that is not part of the protocol. The git
backend and `prepare/apply.py` both spawn children and both need the same answer, so
they ask here rather than each carrying a copy of the platform branch — which is the
same reason the editor launch is here. It is a module-level function, not a method: a
seam is something tests replace, and a test that replaced *this* would be asserting its
own arithmetic.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

# Win32's CREATE_NEW_PROCESS_GROUP. Written out rather than read from `subprocess`,
# which only defines it on Windows: naming the value here is what lets the Windows
# branch below be exercised from a macOS machine, and `test_the_flag_named_here_is_
# the_one_windows_actually_defines` is what stops the two drifting apart.
_CREATE_NEW_PROCESS_GROUP = 0x0000_0200


class Detached(TypedDict, total=False):
    """How to ask for a child the terminal's Ctrl-C cannot reach."""

    start_new_session: bool
    creationflags: int


def detached_child() -> Detached:
    """The `subprocess` keywords that put a child outside lane's own signal group.

    Every spawn in lane wants this and every spawn asks for it here. The terminal
    delivers Ctrl-C to the whole foreground group, so without it a `git worktree
    remove` in flight is killed half-way whatever lane decides to do with its own copy
    of the signal — and deferring that signal (`lane.interrupts`) would buy nothing.
    lane still owns the child's lifetime: an interrupt it does not defer unwinds
    `subprocess.run`, which kills the child on the way out.

    **The two platforms spell it differently, and one of them spells the other's
    silently wrong.** `start_new_session=True` on Windows is accepted and does nothing
    — CPython's `_execute_child` there names the parameter `unused_start_new_session` —
    so a single shared keyword would look correct, pass review, and leave every Windows
    user's git in lane's own console group. `CREATE_NEW_PROCESS_GROUP` is the real
    equivalent: a process created with it does not receive the console's Ctrl-C.
    """
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


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
                **detached_child(),
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
                    **detached_child(),
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
                    **detached_child(),
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
