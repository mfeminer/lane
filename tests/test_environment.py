"""Spawning a child the terminal's Ctrl-C cannot reach, on either kind of system.

This is one behaviour with two spellings. On POSIX it is `start_new_session=True`; on
Windows that keyword is **accepted and ignored** — CPython's own `_execute_child` names
its parameter `unused_start_new_session` — so passing it there buys nothing at all and
fails silently, which is the worst way for an isolation property to stop holding.

Both spellings are asserted here, and the places that spawn are asserted to ask for
whichever one this platform uses rather than writing it out again. Forgetting one call
site is exactly how the terminal would get to kill git half-way through a removal.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lane import environment

WINDOWS = sys.platform == "win32"


def test_a_posix_child_is_asked_for_its_own_session() -> None:
    if WINDOWS:
        pytest.skip("POSIX spelling")
    assert environment.detached_child() == {"start_new_session": True}


def test_a_windows_child_is_asked_for_its_own_process_group_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branch a macOS machine cannot reach, and the reason it has to exist: Windows
    takes `start_new_session` without complaint and does nothing with it."""
    monkeypatch.setattr(sys, "platform", "win32")

    asked = environment.detached_child()

    assert asked == {"creationflags": 0x0000_0200}, "CREATE_NEW_PROCESS_GROUP"
    assert "start_new_session" not in asked, "it would be silently ignored"


def test_the_flag_named_here_is_the_one_windows_actually_defines() -> None:
    """The value is written out so the branch above can be exercised from any platform.
    A wrong constant would isolate nothing and say nothing."""
    if not WINDOWS:
        pytest.skip("only Windows defines it")
    assert environment.detached_child() == {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
    }


def test_a_detached_child_really_is_out_of_lanes_group_on_windows() -> None:
    """The real thing, on a real Windows runner.

    A console control event can only be sent to a process **group**, addressed by the
    pid of the process that founded it. So a child that accepts `CTRL_BREAK_EVENT`
    addressed to its own pid is by definition the root of its own group — and a child
    still sitting in lane's group could not be addressed that way at all.
    """
    if not WINDOWS:
        pytest.skip("Windows process groups")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        **environment.detached_child(),
    )
    try:
        os.kill(child.pid, signal.CTRL_BREAK_EVENT)
        deadline = time.monotonic() + 15
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert child.poll() is not None, "it founded its own group and took the break"
    finally:
        if child.poll() is None:  # pragma: no cover - only on a failure
            child.kill()
        child.wait(timeout=15)


# -- every place that spawns asks for it -----------------------------------------


def _capture(monkeypatch: pytest.MonkeyPatch, name: str) -> list[dict[str, object]]:
    """Record the keyword arguments lane hands to `subprocess`, and still run it."""
    seen: list[dict[str, object]] = []
    real = getattr(subprocess, name)

    def recording(*args: object, **kwargs: object) -> object:
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, name, recording)
    return seen


def test_git_is_spawned_detached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lane.git.cli_backend import CliGitBackend

    seen = _capture(monkeypatch, "run")
    CliGitBackend().is_repository(tmp_path)

    assert seen, "git was never spawned"
    for kwargs in seen:
        assert environment.detached_child().items() <= kwargs.items()


def test_a_prepared_command_is_spawned_detached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lane.prepare import apply

    seen = _capture(monkeypatch, "run")
    apply.run(f"{sys.executable} -c pass", tmp_path)

    assert seen, "the command was never spawned"
    for kwargs in seen:
        assert environment.detached_child().items() <= kwargs.items()


def test_the_editor_is_launched_detached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fire-and-forget, and still out of the group: quitting lane must not take the
    editor with it."""
    seen: list[dict[str, object]] = []

    class _Fake:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args
            seen.append(kwargs)

    monkeypatch.setattr(subprocess, "Popen", _Fake)

    launch = environment.RealEnvironment().launch_editor(sys.executable, tmp_path)

    assert launch.launched
    assert seen
    assert environment.detached_child().items() <= seen[0].items()
