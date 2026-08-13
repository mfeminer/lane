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

import os
from pathlib import Path

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
    """The same reason git gets `start_new_session`: the terminal's Ctrl-C reaches
    lane and nothing else, so lane decides what happens to the child rather than the
    terminal killing it out from under a spinner."""
    outcome = apply.run("sh -c 'ps -o pgid= -p $$'", tmp_path)

    assert outcome.ok
    assert int(outcome.detail.strip()) != os.getpgrp()


# -- measuring -------------------------------------------------------------------


def test_measure_reports_a_size_for_a_tree_and_nothing_for_a_missing_path(
    tmp_path: Path,
) -> None:
    source = _tree(tmp_path / "source")
    (source / "big").write_bytes(b"\0" * 200_000)

    assert (apply.measure(source) or 0) >= 200_000
    assert apply.measure(tmp_path / "nope") is None


def test_size_phrase_reads_like_a_size() -> None:
    assert apply.size_phrase(None) == "—"
    assert apply.size_phrase(0) == "0 B"
    assert apply.size_phrase(1_400) == "1.4 KB"
    assert apply.size_phrase(340 * 1000**2) == "340 MB"
    assert apply.size_phrase(1_200 * 1000**2) == "1.2 GB"


# -- whether cloning can happen at all -------------------------------------------


def test_cloning_is_available_within_one_volume(tmp_path: Path) -> None:
    """What doctor and settings both ask. On this machine the temporary directory is
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
