"""What preparation will ask and what it will do, decided before either happens.

The two properties worth holding on to: **only paths with no answer are ever asked
about**, so a second lane in the same project asks nothing; and **an answered path that
is already in the lane is left alone** unless the user asked for it to be refreshed,
because that path is the lane's now.
"""

from __future__ import annotations

from pathlib import Path

from lane import prepare
from lane.prepare import Step, Verb


def _lane(tmp_path: Path) -> Path:
    lane = tmp_path / "lane"
    lane.mkdir()
    return lane


def test_a_path_with_no_answer_becomes_something_to_ask_about(tmp_path: Path) -> None:
    plan = prepare.plan(
        project="acme",
        steps=(),
        ignored=["node_modules", ".env"],
        lane_path=_lane(tmp_path),
        linkable=frozenset({".env"}),
    )

    assert [candidate.path for candidate in plan.candidates] == ["node_modules", ".env"]
    assert plan.effects == ()
    assert plan.anything_to_do


def test_a_path_with_an_answer_is_never_asked_about_again(tmp_path: Path) -> None:
    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.SKIP, path="node_modules"),),
        ignored=["node_modules"],
        lane_path=_lane(tmp_path),
    )

    assert plan.candidates == ()
    assert plan.effects == (), "skip has nothing to do"
    assert not plan.anything_to_do


def test_a_candidate_says_whether_the_path_is_already_in_the_lane(tmp_path: Path) -> None:
    """Which changes what the answer means, so the screen shows it."""
    lane = _lane(tmp_path)
    (lane / "node_modules").mkdir()

    plan = prepare.plan(
        project="acme",
        steps=(),
        ignored=["node_modules", "vendor"],
        lane_path=lane,
    )

    present = {candidate.path: candidate.present for candidate in plan.candidates}
    assert present == {"node_modules": True, "vendor": False}


def test_link_is_dropped_from_the_cycle_when_git_says_a_symlink_is_not_ignored(
    tmp_path: Path,
) -> None:
    """`node_modules/` matches directories only, so a symlink of that name shows up as
    an untracked file — `● 1 uncommitted` in the listing, over a link the user asked
    for. git answers this, so lane does not offer what it cannot deliver."""
    plan = prepare.plan(
        project="acme",
        steps=(),
        ignored=["node_modules", "dist"],
        lane_path=_lane(tmp_path),
        linkable=frozenset({"dist"}),
    )

    cycles = {candidate.path: candidate.cycle() for candidate in plan.candidates}
    assert cycles["node_modules"] == (Verb.SKIP, Verb.CLONE)
    assert cycles["dist"] == (Verb.SKIP, Verb.CLONE, Verb.LINK)


def test_a_clone_that_is_already_there_does_nothing(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    (lane / "node_modules").mkdir()

    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.CLONE, path="node_modules"),),
        ignored=["node_modules"],
        lane_path=lane,
    )

    assert plan.effects == ()


def test_a_refreshing_clone_overwrites_what_is_there(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    (lane / "node_modules").mkdir()
    step = Step(project="acme", verb=Verb.CLONE, path="node_modules", refresh=True)

    plan = prepare.plan(project="acme", steps=(step,), ignored=["node_modules"], lane_path=lane)

    assert [(e.subject, e.overwrites) for e in plan.effects] == [("node_modules", True)]
    assert plan.effects[0].phrase() == "Replacing node_modules…"


def test_a_clone_that_is_missing_is_cloned_without_being_asked_about(tmp_path: Path) -> None:
    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.CLONE, path="node_modules"),),
        ignored=["node_modules"],
        lane_path=_lane(tmp_path),
    )

    assert [(e.subject, e.overwrites) for e in plan.effects] == [("node_modules", False)]
    assert plan.candidates == ()
    assert plan.effects[0].phrase() == "Cloning node_modules…"


def test_a_link_that_is_already_a_link_is_left_alone(tmp_path: Path) -> None:
    """Even a link whose target has gone. It is *there*, it is the lane's, and lane
    does not silently take it away — `exists()` alone would follow it and call it
    missing."""
    lane = _lane(tmp_path)
    (lane / ".env").symlink_to(tmp_path / "gone")

    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.LINK, path=".env"),),
        ignored=[".env"],
        lane_path=lane,
    )

    assert plan.effects == ()


def test_a_command_guarded_by_a_path_that_exists_does_not_run(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    (lane / "node_modules").mkdir()
    step = Step(
        project="acme",
        verb=Verb.RUN,
        command="install-things",
        unless="node_modules",
    )

    plan = prepare.plan(project="acme", steps=(step,), ignored=[], lane_path=lane)

    assert plan.effects == ()


def test_a_command_with_no_guard_runs_every_time(tmp_path: Path) -> None:
    step = Step(project="acme", verb=Verb.RUN, command="install-things")

    plan = prepare.plan(project="acme", steps=(step,), ignored=[], lane_path=_lane(tmp_path))

    assert [e.subject for e in plan.effects] == ["install-things"]
    assert plan.effects[0].phrase() == "Running install-things…"


def test_a_command_whose_guard_is_missing_runs(tmp_path: Path) -> None:
    step = Step(project="acme", verb=Verb.RUN, command="install-things", unless="node_modules")

    plan = prepare.plan(project="acme", steps=(step,), ignored=[], lane_path=_lane(tmp_path))

    assert [e.subject for e in plan.effects] == ["install-things"]


def test_nothing_to_ask_and_nothing_to_do_is_an_empty_plan(tmp_path: Path) -> None:
    """The common case — entering a lane that is already ready — and it has to cost
    nothing: no screen, no spinner, no line."""
    lane = _lane(tmp_path)
    (lane / "node_modules").mkdir()

    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.CLONE, path="node_modules"),),
        ignored=["node_modules"],
        lane_path=lane,
    )

    assert not plan.anything_to_do
    assert plan.problem is None


def test_a_step_for_a_path_git_no_longer_ignores_still_applies(tmp_path: Path) -> None:
    """Discovery only reports what exists in the main clone. A path that has been
    cleaned away there is not a reason to forget the answer about it — but there is
    nothing to copy, so the step reports rather than pretending."""
    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.CLONE, path="node_modules"),),
        ignored=[],
        lane_path=_lane(tmp_path),
    )

    assert [e.subject for e in plan.effects] == ["node_modules"]


def test_the_settings_view_of_a_step_says_what_was_stored(tmp_path: Path) -> None:
    """Settings has no lane in hand, so it describes the answer rather than an effect."""
    del tmp_path
    assert Step(project="a", verb=Verb.CLONE, path="x").describe() == "clone"
    assert Step(project="a", verb=Verb.CLONE, path="x", refresh=True).describe() == (
        "clone, refreshed"
    )
    assert Step(project="a", verb=Verb.LINK, path="x").describe() == "link"
    assert Step(project="a", verb=Verb.SKIP, path="x").describe() == "skip"
    assert Step(project="a", verb=Verb.RUN, command="c", directory="web").describe() == (
        "run · web"
    )
    assert Step(project="a", verb=Verb.RUN, command="c").describe() == "run"
