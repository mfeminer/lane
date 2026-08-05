"""The two flags lane accepts, and the refusal for everything else.

`--version` and `--help` are answered before any prerequisite is consulted, so
these tests deliberately construct no environment at all.
"""

from __future__ import annotations

import re

import pytest

from lane import __version__, cli


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


def test_help_documents_exactly_the_two_flags_and_says_lane_is_interactive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(["--help"])

    out = capsys.readouterr().out
    assert code == 0
    assert "--version" in out
    assert "--help" in out
    # The point of the help text: there is nothing else to type.
    assert "interactive" in out.lower()
    # And no subcommand may ever be advertised here.
    for absent in ("open", "close", "doctor", "changelog"):
        assert f"lane {absent}" not in out


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


def test_a_subcommand_is_refused_and_named(capsys: pytest.CaptureFixture[str]) -> None:
    """The bash version took `lane open`. This one must say that it does not."""
    code = cli.main(["open"])

    captured = capsys.readouterr()
    assert code != 0
    assert "open" in captured.err
    assert "subcommand" in captured.err.lower()


def test_an_unknown_flag_is_refused_and_named(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--wat"])

    captured = capsys.readouterr()
    assert code != 0
    assert "--wat" in captured.err


def test_a_refusal_does_not_print_a_usage_error_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """argparse's own error path must not leak: the message is lane's own prose."""
    cli.main(["--wat"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unrecognized arguments" not in captured.err
