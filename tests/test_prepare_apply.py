"""Cloning, linking and running — against the real filesystem.

Nothing here is faked. `clonefile(2)` either works on this machine or it does not,
and both outcomes are asserted: what matters is not that a clone is cheap but that
lane knows which of the two it got, because the expensive one costs real disk and
the user configured it expecting free.

The `run` verb is exercised with genuinely harmless commands. `Environment` keeps the
editor launch because that is fire-and-forget and must never happen in a test; a
prepared command is waited on and its exit code read, which `true` and `touch` can
demonstrate honestly.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

from lane.prepare import apply


def _tree(root: Path) -> Path:
    """A small directory tree, deep enough that a shallow copy would be caught."""
    root.mkdir(parents=True)
    (root / "top.txt").write_text("top\n")
    (root / "deep").mkdir()
    (root / "deep" / "inner.txt").write_text("inner\n")
    return root


# -- clone -----------------------------------------------------------------------


def test_clone_reproduces_a_tree_and_the_copy_is_independent(tmp_path: Path) -> None:
    source = _tree(tmp_path / "source")
    target = tmp_path / "target"

    outcome = apply.clone(source, target)

    assert outcome.ok
    assert (target / "top.txt").read_text() == "top\n"
    assert (target / "deep" / "inner.txt").read_text() == "inner\n"

    (target / "top.txt").write_text("changed\n")
    assert (source / "top.txt").read_text() == "top\n", "copy-on-write, not a shared file"


def test_clone_copies_a_single_file_too(tmp_path: Path) -> None:
    source = tmp_path / ".env"
    source.write_text("SECRET=1\n")

    assert apply.clone(source, tmp_path / "lane" / ".env").ok
    assert (tmp_path / "lane" / ".env").read_text() == "SECRET=1\n"


def test_clone_over_an_existing_target_replaces_it(tmp_path: Path) -> None:
    source = _tree(tmp_path / "source")
    target = _tree(tmp_path / "target")
    (target / "stale.txt").write_text("stale\n")

    assert apply.clone(source, target).ok

    assert not (target / "stale.txt").exists(), "the old tree went, whole"
    assert (target / "deep" / "inner.txt").read_text() == "inner\n"


def test_clone_stages_beside_the_target_so_it_is_never_half_there(tmp_path: Path) -> None:
    """The reason preparation needs no rollback logic and no deferred interrupt: the
    target is the old thing or the new thing, never half of one. Asserted by failing
    the swap and finding the original still whole."""
    source = _tree(tmp_path / "source")
    target = _tree(tmp_path / "target")
    (target / "mine.txt").write_text("mine\n")

    def explode(_source: Path, _target: Path) -> None:
        raise OSError("the swap failed")

    outcome = apply.clone(source, target, _swap=explode)

    assert not outcome.ok
    assert (target / "mine.txt").read_text() == "mine\n", "untouched by a failed clone"
    assert list(target.parent.glob("*.lane-partial*")) == [], "and nothing staged left behind"


def test_clone_clears_a_staged_path_an_earlier_run_left(tmp_path: Path) -> None:
    source = _tree(tmp_path / "source")
    target = tmp_path / "target"
    stranded = apply.staged_path(target)
    _tree(stranded)
    (stranded / "junk.txt").write_text("junk\n")

    assert apply.clone(source, target).ok

    assert not (target / "junk.txt").exists()
    assert not stranded.exists()


def test_clone_reports_whether_copy_on_write_actually_happened(tmp_path: Path) -> None:
    """The whole point of not shelling out to `cp -c`, which falls back silently."""
    source = _tree(tmp_path / "source")

    cloned = apply.clone(source, tmp_path / "cloned")
    copied = apply.clone(source, tmp_path / "copied", _clone_file=None)

    assert cloned.ok and copied.ok
    assert copied.copied, "a real copy says so"
    assert (tmp_path / "copied" / "deep" / "inner.txt").read_text() == "inner\n"
    if apply.cloning_available(tmp_path, tmp_path):
        assert not cloned.copied, "on a cloning volume it must not have fallen back"


def test_clone_reports_a_missing_source_rather_than_raising(tmp_path: Path) -> None:
    outcome = apply.clone(tmp_path / "nope", tmp_path / "target")
    assert not outcome.ok
    assert "nope" in outcome.detail


# -- run -------------------------------------------------------------------------


def test_run_runs_a_command_in_the_given_directory(tmp_path: Path) -> None:
    where = tmp_path / "web"
    where.mkdir()

    outcome = apply.run("touch made-here", where)

    assert outcome.ok
    assert (where / "made-here").exists()


def test_run_reports_a_failing_command_with_its_output(tmp_path: Path) -> None:
    outcome = apply.run("sh -c 'echo it went wrong >&2; exit 3'", tmp_path)

    assert not outcome.ok
    assert "exit 3" in outcome.detail or "3" in outcome.detail
    assert "it went wrong" in outcome.detail


def test_run_reports_a_command_that_is_not_there(tmp_path: Path) -> None:
    outcome = apply.run("definitely-not-a-real-command --now", tmp_path)
    assert not outcome.ok
    assert "definitely-not-a-real-command" in outcome.detail


def test_run_reports_a_missing_directory_rather_than_raising(tmp_path: Path) -> None:
    outcome = apply.run("true", tmp_path / "nope")
    assert not outcome.ok


def test_run_leaves_the_command_out_of_lanes_process_group(tmp_path: Path) -> None:
    """The same reason git is detached: the terminal's Ctrl-C reaches lane and nothing
    else, so lane decides what happens to the child rather than the terminal killing it
    out from under a spinner.

    POSIX only — `getpgrp` is. The Windows half of the same property is asserted for
    real in `test_environment.py`."""
    if sys.platform == "win32":
        pytest.skip("POSIX process groups — see tests/test_environment.py")
    outcome = apply.run("sh -c 'ps -o pgid= -p $$'", tmp_path)

    assert outcome.ok
    assert int(outcome.detail.strip()) != os.getpgrp()


def test_a_windows_path_in_a_configured_command_survives_being_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`shlex.split` is POSIX-mode: a backslash escapes the next character. On Windows a
    backslash is a path separator, so `C:\\tools\\thing.exe` came apart into
    `C:toolsthing.exe` — and the failure a user sees is "that command is not there",
    about a path they can see with their own eyes."""
    monkeypatch.setattr(sys, "platform", "win32")

    assert apply.split_command(r"C:\tools\thing.exe --flag") == [
        r"C:\tools\thing.exe",
        "--flag",
    ]


def test_a_quoted_windows_path_with_a_space_stays_one_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`C:\\Program Files` is where half of Windows lives, so quoting has to work — and
    the quotes must not survive into the argument, or the program named is a file whose
    name begins with a quotation mark."""
    monkeypatch.setattr(sys, "platform", "win32")

    assert apply.split_command(r'"C:\Program Files\node\npm.cmd" install') == [
        r"C:\Program Files\node\npm.cmd",
        "install",
    ]


def test_elsewhere_a_command_is_split_exactly_as_it_always_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented escape hatch is `sh -c '…'`, and it has to keep working."""
    monkeypatch.setattr(sys, "platform", "darwin")

    assert apply.split_command("sh -c 'echo hi'") == ["sh", "-c", "echo hi"]


def test_an_unbalanced_quote_is_still_refused_rather_than_guessed_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    outcome = apply.run('thing "unbalanced', tmp_path)

    assert not outcome.ok
    assert "could not be read" in outcome.detail


# -- measuring -------------------------------------------------------------------


def test_measure_reports_a_size_for_a_tree_and_nothing_for_a_missing_path(
    tmp_path: Path,
) -> None:
    source = _tree(tmp_path / "source")
    (source / "big").write_bytes(b"\0" * 200_000)

    assert (apply.measure(source) or 0) >= 200_000
    assert apply.measure(tmp_path / "nope") is None


def test_measure_adds_up_exactly_the_bytes_the_files_hold(tmp_path: Path) -> None:
    """An exact number, and the same one on every platform — which `du -sk` never was:
    it answers in block-rounded kilobytes, and it does not exist on Windows at all."""
    tree = tmp_path / "tree"
    (tree / "deep" / "deeper").mkdir(parents=True)
    (tree / "a.bin").write_bytes(b"\0" * 1_000)
    (tree / "deep" / "b.bin").write_bytes(b"\0" * 2_345)
    (tree / "deep" / "deeper" / "c.bin").write_bytes(b"\0" * 7)

    assert apply.measure(tree) == 1_000 + 2_345 + 7


def test_measure_answers_for_a_single_file_too(tmp_path: Path) -> None:
    """The screen asks about paths, and `.env` is a path."""
    one = tmp_path / ".env"
    one.write_bytes(b"\0" * 42)

    assert apply.measure(one) == 42


def test_measure_never_follows_a_link_out_of_the_path(tmp_path: Path) -> None:
    """A linked `node_modules` points into the main clone. Following it would report the
    main clone's size as the lane's, and this number exists to stop somebody bringing in
    twenty gigabytes by accident — the one thing it must never understate by walking
    somewhere else."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "huge.bin").write_bytes(b"\0" * 500_000)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "small.bin").write_bytes(b"\0" * 10)
    (tree / "linked").symlink_to(outside, target_is_directory=True)

    assert apply.measure(tree) == 10


def test_measure_reports_what_it_could_reach_rather_than_giving_up(tmp_path: Path) -> None:
    """One unreadable directory in a tree of hundreds is not a reason to answer `—` for
    the whole path. A short number is more use than no number.

    POSIX only, because making a directory unreadable is: `chmod` on Windows sets a
    read-only attribute at best and cannot take read access away, which is the same
    measured fact `config.keep_private` is built on."""
    if sys.platform == "win32":
        pytest.skip("a mode cannot remove read access on Windows")
    tree = tmp_path / "tree"
    shut = tree / "shut"
    shut.mkdir(parents=True)
    (tree / "readable.bin").write_bytes(b"\0" * 64)
    (shut / "hidden.bin").write_bytes(b"\0" * 1_000)
    shut.chmod(0o000)
    try:
        assert apply.measure(tree) == 64
    finally:
        shut.chmod(0o700)


def test_size_phrase_reads_like_a_size() -> None:
    assert apply.size_phrase(None) == "—"
    assert apply.size_phrase(0) == "0 B"
    assert apply.size_phrase(1_400) == "1.4 KB"
    assert apply.size_phrase(340 * 1000**2) == "340 MB"
    assert apply.size_phrase(1_200 * 1000**2) == "1.2 GB"


# -- loading clonefile at all ----------------------------------------------------


def test_clonefile_is_not_even_looked_for_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """`clonefile(2)` is a macOS system call, and looking for it elsewhere is not free:
    `ctypes.CDLL(None)` — the form that keeps this working inside a PyInstaller bundle —
    raises **TypeError** on Windows, which is neither of the errors this used to catch.
    That happens at import time, so lane did not start at all; the fix is to ask the
    question only where it has an answer."""

    def refuse(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("no library should be opened off macOS")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "CDLL", refuse)

    assert apply._load_clonefile() is None


def test_clonefile_is_still_looked_for_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """And the gate must not be so tight that macOS stops asking — which would turn
    every clone into a real copy without a word about it."""
    asked: list[object] = []
    real = ctypes.CDLL

    def watching(*args: object, **kwargs: object) -> object:
        asked.append(args)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ctypes, "CDLL", watching)

    apply._load_clonefile()

    assert asked, "macOS must still look for the symbol"


# -- whether cloning can happen at all -------------------------------------------


def test_cloning_is_available_within_one_volume(tmp_path: Path) -> None:
    """What doctor and config both ask. On this machine the temporary directory is
    on the boot volume, so the answer is whatever that volume supports — and it has
    to be the *same* answer `clone` itself gets."""
    available = apply.cloning_available(tmp_path, tmp_path)
    outcome = apply.clone(_tree(tmp_path / "source"), tmp_path / "target")

    assert outcome.ok
    assert available is not outcome.copied


def test_cloning_is_unavailable_across_volumes(tmp_path: Path) -> None:
    """Different volumes cannot clone, ever — `clonefile` answers EXDEV, which is the whole
    reason lane calls it rather than `cp -c`. The device numbers are injected because
    mounting a second volume is not something a test may do."""
    far_away = tmp_path / "far-away"
    far_away.mkdir()

    assert not apply.cloning_available(
        tmp_path, far_away, _device=lambda path: 1 if path == far_away else 2
    )


def test_a_lanes_folder_that_does_not_exist_yet_is_still_answered(tmp_path: Path) -> None:
    """It is absent until the first lane is opened, and the question is about *volumes* —
    so the nearest existing ancestor is the honest answer, not "I cannot tell you"."""
    assert apply.cloning_available(tmp_path, tmp_path / "Lanes") == apply.cloning_available(
        tmp_path, tmp_path
    )


def test_the_probe_leaves_nothing_behind(tmp_path: Path) -> None:
    apply.cloning_available(tmp_path, tmp_path)
    assert list(tmp_path.iterdir()) == []
