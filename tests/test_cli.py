"""The command-line surface: the two flags, the five subcommands, and the refusals.

`--version` and `--help` are answered before any prerequisite is consulted, so those
tests deliberately construct no environment at all.

lane took no subcommands until scripts and agents had to drive it; AGENTS.md carries
that reversal. What did **not** change is that a bare `lane` is the interactive
session and still needs a terminal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lane import __version__, cli
from tests.fakes import FakeEnvironment


def test_version_flag_reports_name_version_and_build(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--version"])

    out = capsys.readouterr().out
    assert code == 0
    assert f"lane {__version__}" in out
    # A fingerprint of the running executable, so two copies of one version differ.
    assert re.search(r"build [0-9a-f]{7}", out), out


def test_short_version_flag_is_the_same(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["-V"]) == 0
    short = capsys.readouterr().out

    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out == short


def test_help_is_argparses_own_rendering_of_the_parser(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Generated, not written by hand — the test that catches the next drift.

    A hand-written paragraph was right for two flags. Five subcommands with their own
    flags each is exactly the list that goes stale when a person maintains it, so the
    parser is the only definition and this asserts against the parser itself.
    """
    from lane.cli import parser as parsing

    code = cli.main(["--help"])

    out = capsys.readouterr().out
    assert code == 0
    assert out == parsing.build().format_help().rstrip() + "\n"


def test_help_lists_every_subcommand_with_its_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lane.cli.parser import COMMANDS

    cli.main(["--help"])

    out = capsys.readouterr().out
    for command in COMMANDS:
        assert command.name in out
    assert "interactive" in out.lower()


def test_short_help_flag_is_the_same(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["-h"]) == 0
    short = capsys.readouterr().out

    assert cli.main(["--help"]) == 0
    assert capsys.readouterr().out == short


def test_help_does_not_reference_q_as_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    """q was removed from the app and must not be mentioned in help."""
    code = cli.main(["--help"])

    out = capsys.readouterr().out
    assert code == 0
    assert "press q" not in out.lower()


def test_an_unknown_subcommand_is_refused_and_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(["wat"])

    captured = capsys.readouterr()
    assert code == cli.EXIT_USAGE
    assert "wat" in captured.err


def test_an_unknown_flag_is_refused_and_named(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--wat"])

    captured = capsys.readouterr()
    assert code != 0
    assert "--wat" in captured.err


def test_a_refusal_says_nothing_at_all_on_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stdout is the machine-readable channel now, so a refusal must leave it empty.

    This used to also require that argparse's own wording never leaked, because lane
    had better prose for the one case there was ("lane takes no subcommands"). With
    five subcommands and a generated `--help`, argparse's wording *is* the consistent
    one — what still matters is which stream it goes to.
    """
    cli.main(["--wat"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--wat" in captured.err


# -- the last resort: an interrupt must never surface as a traceback --------------


def test_an_interrupt_reaching_the_boundary_exits_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The session reports the interruptions it can see and carries on. This is the
    backstop for the ones it cannot — nothing lane does may end in a traceback."""
    from lane import app

    def interrupted(environment: object) -> int:
        del environment
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "run", interrupted)

    code = cli.main([], environment=FakeEnvironment())

    # 130 is what a shell reports for a process killed by SIGINT.
    assert code == 130
    assert "traceback" not in capsys.readouterr().err.lower()


def test_each_subcommand_prints_its_own_flags_from_the_parser(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`lane close --help` is that subparser's own rendering, not prose beside it."""
    from lane.cli import parser as parsing

    for command in parsing.COMMANDS:
        assert cli.main([command.name, "--help"]) == 0
        printed = capsys.readouterr().out
        expected = parsing.subparser(command.name).format_help().rstrip() + "\n"
        assert printed == expected


def test_the_close_help_names_the_flags_that_exist(capsys: pytest.CaptureFixture[str]) -> None:
    """One assertion that reads the flags rather than the mechanism, so that a flag
    quietly disappearing is caught by something other than a self-referential diff."""
    cli.main(["close", "--help"])

    out = capsys.readouterr().out
    for flag in ("--rescue", "--no-rescue", "--delete-branch", "--keep-branch", "--yes"):
        assert flag in out


# -- the exit-code table ----------------------------------------------------------
# A public interface: a script branches on these, so they are asserted rather than
# left to be discovered, and an existing one is never renumbered.


def test_the_exit_codes_are_the_documented_ones() -> None:
    assert (cli.EXIT_OK, cli.EXIT_REFUSED, cli.EXIT_USAGE) == (0, 1, 2)
    assert (cli.EXIT_NO_TTY, cli.EXIT_NOT_FOUND, cli.EXIT_INTERRUPTED) == (3, 4, 130)


def test_a_lane_taking_subcommand_with_no_lane_says_what_to_name(
    xdg: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg

    code = cli.main(["close"], environment=FakeEnvironment(interactive=False))

    err = capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert "<project>/<lane>" in err
