"""lane requires a terminal — and says so rather than half-working.

Driven entirely through a faked Environment. The real terminal is never touched.
"""

from __future__ import annotations

import sys

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


# -- lane's own output is UTF-8, and a redirect must not be able to break it -------


class _Stream:
    """A stream that records being reconfigured, and refuses what it cannot encode."""

    def __init__(self, encoding: str = "cp1252") -> None:
        self.encoding = encoding
        self.reconfigured: list[tuple[str, str]] = []
        self.written: list[str] = []

    def reconfigure(self, *, encoding: str, errors: str) -> None:
        self.encoding = encoding
        self.reconfigured.append((encoding, errors))

    def write(self, text: str) -> int:
        text.encode(self.encoding)  # what a real stream would do, and did
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def test_lanes_output_streams_are_asked_for_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """`lane doctor > report.txt` on Windows died with
    `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'` — the tick
    doctor puts in front of every healthy line. Redirected output there is the machine's
    code page, and lane's screens are made of marks and box glyphs on purpose, so the
    one thing lane can be sure of is that its own output is UTF-8. `replace` as well, so
    an exotic console degrades to a question mark rather than a traceback."""
    out, err = _Stream(), _Stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    cli.main(["--version"], environment=FakeEnvironment(interactive=False))

    assert out.reconfigured == [("utf-8", "replace")]
    assert err.reconfigured == [("utf-8", "replace")]


def test_a_stream_that_cannot_be_reconfigured_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pytest's own capture, a pipe someone wrapped, an embedding — none of them owe
    lane a `reconfigure`, and lane refusing to start over it would be absurd."""

    class _Plain:
        def write(self, text: str) -> int:
            return len(text)

        def flush(self) -> None:
            return None

        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdout", _Plain())
    monkeypatch.setattr(sys, "stderr", _Plain())

    assert cli.main(["--version"], environment=FakeEnvironment(interactive=False)) == 0
