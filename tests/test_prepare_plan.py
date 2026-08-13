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


# -- the tree: the top of it first, not two hundred rows of leaves ----------------


def _candidates(*paths: str) -> tuple[prepare.Candidate, ...]:
    return tuple(prepare.Candidate(path=path) for path in paths)


def _labels(items: tuple[prepare.Item, ...]) -> list[str]:
    return [item.label for item in items]


def test_a_directory_of_loose_ignored_files_becomes_one_folder(tmp_path: Path) -> None:
    """`--directory` collapses a *fully* ignored directory, but one tracked file in it
    stops that — and then git reports every ignored file inside separately. A real
    repository produced 55 rows from four ignore patterns that way."""
    del tmp_path
    rows = prepare.tree(_candidates(*[f"logs/day{n}.log" for n in range(1, 41)]))

    assert len(rows) == 1
    folder = rows[0]
    assert isinstance(folder, prepare.Group)
    assert folder.directory == "logs"
    assert len(folder.candidates) == 40
    assert folder.label == "logs/ · 40 ignored paths"


def test_a_folder_holds_its_children_and_they_hold_theirs(tmp_path: Path) -> None:
    """One level of the tree per screen: entering a folder shows what is directly under
    it, which may be more folders. The rows are the branching points, not the leaves."""
    del tmp_path
    leaves = ("node_modules", "dist", ".env")
    paths = [f"packages/p{n}/{leaf}" for n in range(1, 6) for leaf in leaves]
    rows = prepare.tree(_candidates(*paths))

    assert _labels(rows) == ["packages/ · 15 ignored paths"]
    packages = rows[0]
    assert isinstance(packages, prepare.Group)
    assert _labels(packages.items) == [f"packages/p{n}/ · 3 ignored paths" for n in range(1, 6)]

    first = packages.items[0]
    assert isinstance(first, prepare.Group)
    assert _labels(first.items) == [f"packages/p1/{leaf}" for leaf in leaves]


def test_two_hundred_ignored_paths_draw_a_handful_of_rows(tmp_path: Path) -> None:
    """The complaint this whole shape answers: choosing among two hundred flat rows is
    not a screen. The top level shows where the tree branches and nothing else."""
    del tmp_path
    paths = [
        f"{top}/pkg{n}/{leaf}"
        for top in ("apps", "packages", "services")
        for n in range(1, 21)
        for leaf in ("node_modules", "dist", ".env")
    ]
    rows = prepare.tree(_candidates(*paths, "node_modules", ".env"))

    assert len(paths) == 180
    assert _labels(rows) == [
        "apps/ · 60 ignored paths",
        "packages/ · 60 ignored paths",
        "services/ · 60 ignored paths",
        "node_modules",
        ".env",
    ]


def test_a_chain_of_directories_with_no_choice_in_it_is_one_row(tmp_path: Path) -> None:
    """A directory with one child is not a choice, and a screen offering it is a
    keystroke that asks nothing. The chain joins up into the row it was always about."""
    del tmp_path
    rows = prepare.tree(_candidates("apps/web/frontend/node_modules"))

    assert _labels(rows) == ["apps/web/frontend/node_modules"]
    assert isinstance(rows[0], prepare.Candidate)


def test_a_level_of_fewer_than_three_rows_is_drawn_in_its_parent(tmp_path: Path) -> None:
    """A folder row costs a keystroke to reach the rows inside it, so it has to save
    more than one to be worth it. Two becomes one: a wash. Three is where it pays."""
    del tmp_path
    assert len(prepare.tree(_candidates("web/.env", "web/.env.local"))) == 2
    assert len(prepare.tree(_candidates("web/.env", "web/.env.local", "web/x.log"))) == 1


def test_a_folder_that_would_open_on_two_rows_is_spliced_into_its_parent(
    tmp_path: Path,
) -> None:
    """The same rule one level up: `apps/` holding a lone file and one folder opens on
    two rows, so those two rows belong on the screen above it."""
    del tmp_path
    rows = prepare.tree(
        _candidates(
            "apps/api/.env",
            "apps/web/.env",
            "apps/web/.env.local",
            "apps/web/app1.log",
            "node_modules",
        )
    )

    assert _labels(rows) == [
        "apps/api/.env",
        "apps/web/ · 3 ignored paths",
        "node_modules",
    ]


def test_a_whole_ignored_directory_is_a_leaf_beside_its_siblings(tmp_path: Path) -> None:
    """`node_modules` is one path with one answer, and the tree says nothing about what
    each path is — it groups on the separators git already put there."""
    del tmp_path
    rows = prepare.tree(_candidates("a/node_modules", "a/b.log", "a/c.log", "a/d.log"))

    assert _labels(rows) == ["a/ · 4 ignored paths"]
    folder = rows[0]
    assert isinstance(folder, prepare.Group)
    assert _labels(folder.items) == ["a/node_modules", "a/b.log", "a/c.log", "a/d.log"]


def test_loose_files_at_the_repository_root_group_under_a_visible_name(tmp_path: Path) -> None:
    del tmp_path
    rows = prepare.tree(_candidates(".env", "debug.log", ".DS_Store"))

    assert _labels(rows) == ["./ · 3 ignored paths"]
    assert isinstance(rows[0], prepare.Group)
    assert rows[0].directory == ""


def test_a_folder_is_folded_whatever_its_paths_were_answered(tmp_path: Path) -> None:
    """A folder used to be opened out when its paths disagreed, because one checkbox
    cannot say "some of these". The mark can (`◐`), so the shape no longer has to."""
    del tmp_path
    rows = prepare.tree(_candidates("w/a", "w/b", "w/c"))

    assert len(rows) == 1
    assert isinstance(rows[0], prepare.Group)
    assert rows[0].label == "w/ · 3 ignored paths"


def test_a_folder_sits_where_its_first_file_was(tmp_path: Path) -> None:
    """Discovery's order is git's, which is sorted, and the screen keeps it — a folder is
    anchored at its first member rather than hoisted or pushed to the end. Otherwise
    `logs/` shows up after `node_modules`, which reads as a shuffle."""
    del tmp_path
    rows = prepare.tree(
        _candidates(
            "coverage",
            *[f"logs/day{n}.log" for n in range(1, 5)],
            "node_modules",
            *[f"web/a{n}.log" for n in range(1, 5)],
        )
    )

    assert _labels(rows) == [
        "coverage",
        "logs/ · 4 ignored paths",
        "node_modules",
        "web/ · 4 ignored paths",
    ]


def test_every_leaf_beneath_a_folder_is_what_it_stands_for(tmp_path: Path) -> None:
    """A folder is presentation and never a step for its directory, so what it stands
    for is every path under it, however deep — that is what one keystroke answers."""
    del tmp_path
    paths = [f"packages/p{n}/{leaf}" for n in range(1, 6) for leaf in ("node_modules", "dist")]
    rows = prepare.tree(_candidates(*paths))
    folder = rows[0]
    assert isinstance(folder, prepare.Group)

    assert len(folder.candidates) == 10
    assert folder.paths[0] == "packages/p1/node_modules"
