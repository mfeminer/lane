"""What preparation will ask and what it will do, decided before either happens.

The two properties worth holding on to: **only paths with no answer are ever asked
about**, so a second lane in the same project asks nothing; and **a path that is already
in the lane is left alone**, whether the answer was given a minute ago or last month,
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


def test_a_clone_that_is_missing_is_cloned_without_being_asked_about(tmp_path: Path) -> None:
    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.CLONE, path="node_modules"),),
        ignored=["node_modules"],
        lane_path=_lane(tmp_path),
    )

    assert [effect.subject for effect in plan.effects] == ["node_modules"]
    assert plan.candidates == ()
    assert plan.effects[0].phrase() == "Cloning node_modules…"


def test_a_path_that_is_a_broken_link_is_still_left_alone(tmp_path: Path) -> None:
    """A symlink whose target has gone — left by an older lane, which had `link` as an
    answer. It is *there*, it is the lane's, and lane does not silently take it away;
    `exists()` alone would follow it and call it missing."""
    lane = _lane(tmp_path)
    (lane / ".env").symlink_to(tmp_path / "gone")

    plan = prepare.plan(
        project="acme",
        steps=(Step(project="acme", verb=Verb.CLONE, path=".env"),),
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
    assert Step(project="a", verb=Verb.CLONE, path="x").describe() == "clone"
    assert Step(project="a", verb=Verb.SKIP, path="x").describe() == "skip"
    assert Step(project="a", verb=Verb.RUN, command="c", directory="web").describe() == (
        "run · web"
    )
    assert Step(project="a", verb=Verb.RUN, command="c").describe() == "run"


# -- grouping: a folder of loose ignored files is one row, not forty ---------------


def _candidates(*paths: str) -> tuple[prepare.Candidate, ...]:
    return tuple(prepare.Candidate(path=path) for path in paths)


def test_a_directory_of_loose_ignored_files_becomes_one_group(tmp_path: Path) -> None:
    """`--directory` collapses a *fully* ignored directory, but one tracked file in it
    stops that — and then git reports every ignored file inside separately. A real
    repository produced 55 rows from four ignore patterns that way."""
    del tmp_path
    rows = prepare.group(_candidates(*[f"logs/day{n}.log" for n in range(1, 41)]))

    assert len(rows) == 1
    group = rows[0]
    assert isinstance(group, prepare.Group)
    assert group.directory == "logs"
    assert len(group.candidates) == 40
    assert group.label == "logs/ · 40 ignored files"


def test_each_directory_groups_separately_and_the_order_is_kept(tmp_path: Path) -> None:
    del tmp_path
    rows = prepare.group(
        _candidates(
            "apps/api/.env",
            "apps/web/.env",
            "apps/web/.env.local",
            "apps/web/app1.log",
            "node_modules",
        )
    )

    assert [row.label for row in rows] == [
        "apps/api/.env",
        "apps/web/ · 3 ignored files",
        "node_modules",
    ], "one row per directory that has several, and lone paths left as themselves"


def test_a_directory_with_only_a_couple_of_files_is_not_grouped(tmp_path: Path) -> None:
    """A group row costs a keystroke to reach the individual answers, so it has to save
    more than one row to be worth it. Two becomes one: a wash. Three is where it pays."""
    del tmp_path
    assert len(prepare.group(_candidates("web/.env", "web/.env.local"))) == 2
    assert len(prepare.group(_candidates("web/.env", "web/.env.local", "web/x.log"))) == 1


def test_a_whole_ignored_directory_is_never_folded_into_a_group(tmp_path: Path) -> None:
    """`node_modules` is one path with one answer. Folding it in with its siblings would
    make a group whose answer means two different things."""
    del tmp_path
    rows = prepare.group(_candidates("a/node_modules", "a/b.log", "a/c.log", "a/d.log"))

    assert [row.label for row in rows] == ["a/ · 4 ignored files"], (
        "grouping is by parent directory and says nothing about what each path is"
    )


def test_loose_files_at_the_repository_root_group_under_a_visible_name(tmp_path: Path) -> None:
    del tmp_path
    rows = prepare.group(_candidates(".env", "debug.log", ".DS_Store"))

    assert [row.label for row in rows] == ["./ · 3 ignored files"]
    assert isinstance(rows[0], prepare.Group)
    assert rows[0].directory == ""


def test_a_folder_whose_paths_disagree_is_not_folded(tmp_path: Path) -> None:
    """One checkbox has two states, so a directory with two paths in and one out has no
    honest tick. It is opened out into its own rows instead of made to lie — which is
    what replaced drilling into a folder to answer it file by file."""
    del tmp_path
    candidates = _candidates("w/a", "w/b", "w/c")

    folded = prepare.group(candidates, checked=frozenset({"w/a", "w/b", "w/c"}))
    assert len(folded) == 1
    assert isinstance(folded[0], prepare.Group)

    opened = prepare.group(candidates, checked=frozenset({"w/a"}))
    assert [item.path for item in opened if isinstance(item, prepare.Candidate)] == [
        "w/a",
        "w/b",
        "w/c",
    ]


def test_a_folder_with_nothing_answered_is_folded(tmp_path: Path) -> None:
    """The screen a path is first answered on has nothing checked, so everything folds —
    a disagreement can only ever arrive from answers already on disk."""
    del tmp_path
    folded = prepare.group(_candidates("w/a", "w/b", "w/c"))

    assert len(folded) == 1
    assert isinstance(folded[0], prepare.Group)
    assert folded[0].label == "w/ · 3 ignored files"


def test_a_group_sits_where_its_first_file_was(tmp_path: Path) -> None:
    """Discovery's order is git's, which is sorted, and the screen keeps it — a group is
    anchored at its first member rather than hoisted or pushed to the end. Otherwise
    `logs/` shows up after `node_modules`, which reads as a shuffle."""
    del tmp_path
    rows = prepare.group(
        _candidates(
            "coverage",
            *[f"logs/day{n}.log" for n in range(1, 5)],
            "node_modules",
            *[f"web/a{n}.log" for n in range(1, 5)],
        )
    )

    assert [row.label for row in rows] == [
        "coverage",
        "logs/ · 4 ignored files",
        "node_modules",
        "web/ · 4 ignored files",
    ]
