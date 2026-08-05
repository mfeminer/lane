"""lane requires a terminal — and says so rather than half-working.

Driven entirely through a faked Environment. The real terminal is never touched.
"""

from __future__ import annotations

import pytest

from lane import __version__, cli
from tests.fakes import FakeEnvironment


def test_without_a_tty_lane_refuses_and_says_it_is_interactive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = FakeEnvironment(interactive=False)

    code = cli.main([], environment=env)

    captured = capsys.readouterr()
    assert code != 0
    assert "interactive" in captured.err.lower()
    assert "terminal" in captured.err.lower()


def test_without_a_tty_version_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    """The one path guaranteed to work in CI."""
    env = FakeEnvironment(interactive=False)

    code = cli.main(["--version"], environment=env)

    captured = capsys.readouterr()
    assert code == 0
    assert f"lane {__version__}" in captured.out
    assert captured.err == ""


def test_without_a_tty_help_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    env = FakeEnvironment(interactive=False)

    code = cli.main(["--help"], environment=env)

    assert code == 0
    assert "--version" in capsys.readouterr().out
