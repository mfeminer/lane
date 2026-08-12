"""Entering a lane: make it ready, then launch the editor.

`enter` used to mean only the second half. A lane is a fresh checkout, so everything
`.gitignore` covers is missing from it — and for some projects that is minutes of hand
work at the exact moment lane is supposed to be getting out of the way.

Two things this file is really protecting:

* **The common case costs one git call and shows nothing.** Entering an already-prepared
  lane must not put a screen between the user and their editor. Counted, not eyeballed.
* **Entering again repairs a preparation that failed or was interrupted.** Nothing is
  recorded per lane, so there is nothing to go stale and nothing to reset.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from lane.actions import enter_lane
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import Lane, LaneMeta, LaneStore
from lane.prepare import Step, Verb
from lane.state import StateStore
from lane.ui.seam import Abandoned
from tests.conftest import build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


class CountingBackend(CliGitBackend):
    """The real backend, counting what it was asked to run.

    Not a fake: every call still reaches git. Counting is how "entering a prepared lane
    costs one git call" is a test rather than a claim.
    """

    def __init__(self) -> None:
        super().__init__()
        self.ran: list[str] = []

    def _run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: int = 120,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.ran.append(args[0])
        return super()._run(args, cwd=cwd, timeout=timeout, stdin=stdin)


def _context(
    *,
    ui: FakeUi,
    projects_root: Path,
    lanes_root: Path,
    backend: CliGitBackend | None = None,
    environment: FakeEnvironment | None = None,
) -> Context:
    return Context(
        ui=ui,
        git=backend or CliGitBackend(),
        github=StubGitHubClient(),
        environment=environment or FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor"),
        config_store=ConfigStore(lanes_root.parent / "cfg"),
        state_store=StateStore(lanes_root.parent / "st"),
    )


def _project(projects_root: Path, name: str = "demo", *, ignore: tuple[str, ...] = ()) -> Path:
    """A real repository under the projects root, with a real `.gitignore`.

    Pushed, not just committed: a lane is created at `origin/<base>`, so a `.gitignore`
    that never left this clone would leave the lane ignoring nothing — which is a real
    situation (a lane on an older base) and not the one these tests are about.
    """
    _origin, clone = build_repo(projects_root / f"_{name}")
    repo = projects_root / name
    clone.rename(repo)
    if ignore:
        (repo / ".gitignore").write_text("".join(f"{line}\n" for line in ignore))
        git(["add", ".gitignore"], cwd=repo)
        git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
        git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    return repo


def _lane(context: Context, repo: Path, name: str = "broken-pagination") -> Lane:
    """A real worktree, made the way `open` makes one."""
    store: LaneStore = context.lane_store()
    path = store.lane_path(repo.name, name)
    context.git.add_worktree_new_branch(repo, path, f"bugfix/{name}", "origin/main")
    meta = LaneMeta(description=name, base="main", created=LaneStore.timestamp(), repo=str(repo))
    store.write_meta(repo.name, name, meta)
    return Lane(project=repo.name, name=name, path=path, meta=meta)


def _tree(root: Path, *names: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names or ("pkg",):
        (root / name).write_text(f"{name}\n")
    return root


# -- the common case: nothing to do ----------------------------------------------


def test_a_lane_with_nothing_to_prepare_shows_nothing_and_costs_one_git_call(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi()
    backend = CountingBackend()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root, backend=backend)
    repo = _project(projects_root)
    lane = _lane(context, repo)

    backend.ran.clear()
    enter_lane.enter(context, lane)

    assert backend.ran == ["ls-files"], "discovery, and nothing else"
    assert ui.asked == [], "no screen between the user and their editor"
    assert [told.kind for told in ui.told] == ["ok"], "just the editor launching"


def test_an_answered_path_that_is_already_there_is_left_alone(
    projects_root: Path, lanes_root: Path
) -> None:
    """**Entering a lane never overwrites what the lane changed** unless the user asked
    for that path to be refreshed."""
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "from-the-main-clone")
    lane = _lane(context, repo)
    _tree(lane.path / "node_modules", "patched-by-hand")
    context.prepare_store().save((Step(project="demo", verb=Verb.CLONE, path="node_modules"),))

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules" / "patched-by-hand").exists()
    assert not (lane.path / "node_modules" / "from-the-main-clone").exists()


# -- the screen -------------------------------------------------------------------


def test_an_unanswered_path_is_asked_about_on_one_screen(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/", ".env"))
    _tree(repo / "node_modules")
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("node_modules" in row for row in rows)
    assert any(".env" in row for row in rows)
    assert any("continue" in row for row in rows)
    assert len(ui.asked) == 1, "one screen, not a queue of questions"


def test_every_row_starts_at_skip_and_continuing_writes_nothing(
    projects_root: Path, lanes_root: Path
) -> None:
    """The default has to be the answer that changes nothing: one Enter records every
    visible answer, including the rows nobody touched."""
    ui = FakeUi(["continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert not (lane.path / "node_modules").exists()
    assert [(s.path, s.verb) for s in context.prepare_store().load().for_project("demo")] == [
        ("node_modules", Verb.SKIP)
    ]
    assert ui.said("remembered")
    assert ui.said("settings")
    assert not any(told.kind in {"error", "progress"} for told in ui.told), (
        "a skip has nothing to apply, so it must not become a step that runs"
    )


def test_the_screen_says_it_will_be_remembered_and_where_to_change_it(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")

    enter_lane.enter(context, _lane(context, repo))

    assert ui.said("Answers are remembered per project")


def test_changing_a_row_to_clone_brings_the_path_in_and_remembers_it(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([("space", "node_modules"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "pkg")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules" / "pkg").read_text() == "pkg\n"
    assert [(s.path, s.verb) for s in context.prepare_store().load().for_project("demo")] == [
        ("node_modules", Verb.CLONE)
    ]


def test_a_second_lane_in_the_same_project_asks_nothing(
    projects_root: Path, lanes_root: Path
) -> None:
    """The whole point of remembering: this is the screen's second appearance, and it
    does not appear."""
    first_ui = FakeUi([("space", "node_modules"), "continue"])
    context = _context(ui=first_ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "pkg")
    enter_lane.enter(context, _lane(context, repo, "first"))

    second_ui = FakeUi()
    context.ui = second_ui
    second = _lane(context, repo, "second")
    enter_lane.enter(context, second)

    assert second_ui.asked == []
    assert (second.path / "node_modules" / "pkg").exists(), "and it was prepared anyway"


def test_space_cycles_through_the_verbs_and_wraps(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi([("space", ".env"), ("space", ".env"), ("space", ".env"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert [s.verb for s in context.prepare_store().load().for_project("demo")] == [Verb.SKIP], (
        "skip → clone → link → skip"
    )
    assert not (lane.path / ".env").exists()


def test_link_is_not_offered_for_a_path_ignored_as_a_directory_only(
    projects_root: Path, lanes_root: Path
) -> None:
    """`node_modules/` matches directories, and a symlink is not one — so linking it
    would put `● 1 uncommitted` in the listing over a link the user asked for. git
    answers this, and the panel says so."""
    ui = FakeUi([("space", "node_modules"), ("space", "node_modules"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert [s.verb for s in context.prepare_store().load().for_project("demo")] == [Verb.SKIP], (
        "two presses went skip → clone → skip, with no link in between"
    )
    assert any("link" in told.text and "not offered" in told.text for told in ui.told)


def test_link_is_offered_for_a_path_ignored_by_name(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi([("space", ".env"), ("space", ".env"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert (lane.path / ".env").is_symlink()
    assert (lane.path / ".env").readlink() == repo / ".env"


def test_a_path_already_in_the_lane_says_the_answer_overwrites_it(
    projects_root: Path, lanes_root: Path
) -> None:
    """The fact that changes what the answer means, on the row, in words — so the
    destructive case names itself before it happens."""
    ui = FakeUi([("space", "node_modules"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "fresh")
    lane = _lane(context, repo)
    _tree(lane.path / "node_modules", "mine")

    enter_lane.enter(context, lane)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("overwrites" in row for row in rows)
    assert (lane.path / "node_modules" / "fresh").exists()
    assert not (lane.path / "node_modules" / "mine").exists(), "the user asked for that"


def test_sizes_arrive_after_the_rows_do(projects_root: Path, lanes_root: Path) -> None:
    """`du` on a large tree is slow, so the rows are complete first and the sizes fill in
    behind — the lanes table's own shape, and its own `fill`."""
    ui = FakeUi(["continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "big").write_bytes(b"\0" * 300_000)
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)
    seen = [told.text for told in ui.told if told.kind == "row"]

    assert any("node_modules" in row and "KB" in row for row in seen), (
        "the size settled before the table was read, which is what `fill` guarantees"
    )


def test_backing_out_of_the_screen_changes_nothing_and_launches_nothing(
    projects_root: Path, lanes_root: Path
) -> None:
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi([FakeUi.ABANDON])
    context = _context(
        ui=ui, projects_root=projects_root, lanes_root=lanes_root, environment=environment
    )
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)

    with pytest.raises(Abandoned):
        enter_lane.enter(context, lane)

    assert not (lane.path / "node_modules").exists()
    assert context.prepare_store().load().steps == (), "nothing remembered either"
    assert environment.launched == []


# -- applying without asking ------------------------------------------------------


def test_a_refreshing_clone_replaces_what_is_there_on_every_enter(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "current")
    lane = _lane(context, repo)
    _tree(lane.path / "node_modules", "stale")
    context.prepare_store().save(
        (Step(project="demo", verb=Verb.CLONE, path="node_modules", refresh=True),)
    )

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules" / "current").exists()
    assert not (lane.path / "node_modules" / "stale").exists()
    assert ui.said("Replacing node_modules")


def test_a_command_runs_when_its_guard_path_is_missing(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root)
    lane = _lane(context, repo)
    context.prepare_store().save(
        (
            Step(
                project="demo",
                verb=Verb.RUN,
                command="touch installed",
                unless="installed",
            ),
        )
    )

    enter_lane.enter(context, lane)
    assert (lane.path / "installed").exists()

    ui.told.clear()
    enter_lane.enter(context, lane)
    assert not ui.said("Running"), "the guard path is there now"


def test_a_command_runs_in_its_configured_directory(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root)
    lane = _lane(context, repo)
    (lane.path / "web").mkdir()
    context.prepare_store().save(
        (Step(project="demo", verb=Verb.RUN, command="touch installed", directory="web"),)
    )

    enter_lane.enter(context, lane)

    assert (lane.path / "web" / "installed").exists()


def test_paths_are_brought_in_before_commands_run(projects_root: Path, lanes_root: Path) -> None:
    """A command usually depends on the paths being in place — a guard on a path that a
    clone is about to satisfy has to see it."""
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)
    context.prepare_store().save(
        (
            Step(
                project="demo",
                verb=Verb.RUN,
                command="touch should-not-run",
                unless="node_modules",
            ),
            Step(project="demo", verb=Verb.CLONE, path="node_modules"),
        )
    )

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules").exists()
    assert not (lane.path / "should-not-run").exists()


# -- when it goes wrong -----------------------------------------------------------


def test_a_failed_step_reports_the_fix_and_the_others_still_run(
    projects_root: Path, lanes_root: Path
) -> None:
    """A lane that is mostly prepared beats a lane you cannot get into, so the editor
    still launches and the remaining steps still run."""
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi()
    context = _context(
        ui=ui, projects_root=projects_root, lanes_root=lanes_root, environment=environment
    )
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)
    context.prepare_store().save(
        (
            Step(project="demo", verb=Verb.CLONE, path="gone-from-the-main-clone"),
            Step(project="demo", verb=Verb.CLONE, path="node_modules"),
        )
    )

    enter_lane.enter(context, lane)

    assert any(told.kind == "error" for told in ui.told)
    assert (lane.path / "node_modules").exists(), "the next step still ran"
    assert environment.launched, "and the editor still opened"


def test_a_failing_command_is_reported_with_what_it_said(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root)
    lane = _lane(context, repo)
    context.prepare_store().save(
        (
            Step(
                project="demo",
                verb=Verb.RUN,
                command="sh -c 'echo no dice >&2; exit 2'",
            ),
        )
    )

    enter_lane.enter(context, lane)

    assert ui.said("no dice")


def test_entering_again_finishes_what_a_failed_preparation_left(
    projects_root: Path, lanes_root: Path
) -> None:
    """Nothing is recorded per lane, so there is nothing to reset — the filesystem is
    the only state, and entering again is the repair."""
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    lane = _lane(context, repo)
    context.prepare_store().save((Step(project="demo", verb=Verb.CLONE, path="node_modules"),))

    enter_lane.enter(context, lane)
    assert any(told.kind == "error" for told in ui.told), "nothing there to clone yet"

    _tree(repo / "node_modules", "pkg")
    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules" / "pkg").exists()


def test_an_interrupt_names_the_step_and_does_not_launch_the_editor(
    projects_root: Path, lanes_root: Path
) -> None:
    """Not deferred: a clone is staged and swapped, so there is no half-populated path
    to protect — and deferring a long install would make Ctrl-C look broken, which is
    the very thing deferral exists to prevent."""
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi()
    context = _context(
        ui=ui, projects_root=projects_root, lanes_root=lanes_root, environment=environment
    )
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)
    context.prepare_store().save((Step(project="demo", verb=Verb.CLONE, path="node_modules"),))

    def interrupted(text: str, work: object) -> object:
        del work
        if text.startswith("Cloning"):
            raise Abandoned
        return None

    context.ui.progress = interrupted  # type: ignore[method-assign, assignment]

    with pytest.raises(Abandoned):
        enter_lane.enter(context, lane)

    assert ui.said("Interrupted while cloning node_modules")
    assert ui.said("Entering the lane again")
    assert environment.launched == []


def test_an_unreadable_answers_file_says_so_and_still_enters(
    projects_root: Path, lanes_root: Path
) -> None:
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi(["continue"])
    context = _context(
        ui=ui, projects_root=projects_root, lanes_root=lanes_root, environment=environment
    )
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")
    lane = _lane(context, repo)
    store = context.prepare_store()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not toml [[[")

    enter_lane.enter(context, lane)

    assert ui.said("Could not read")
    assert environment.launched


# -- secrets ----------------------------------------------------------------------


def test_cloning_a_path_that_looks_like_secrets_says_link_keeps_one_copy(
    projects_root: Path, lanes_root: Path
) -> None:
    """Copying a `.env` into every lane multiplies the number of places a secret lives.
    Closing the lane removes them — a refused close does not."""
    ui = FakeUi([("space", ".env"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")

    enter_lane.enter(context, _lane(context, repo))

    assert ui.said("looks like it holds secrets")
    assert ui.said("link")


def test_a_path_that_does_not_look_like_secrets_says_nothing_about_them(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([("space", "node_modules"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")

    enter_lane.enter(context, _lane(context, repo))

    assert not ui.said("secrets")


# -- what preparation must not disturb --------------------------------------------


def test_a_prepared_lane_is_still_clean_to_git(projects_root: Path, lanes_root: Path) -> None:
    """Only paths git ignores in the lane are ever written, which is what keeps
    preparation out of the listing's `state` cell and out of the close flow's checks."""
    ui = FakeUi([("space", "node_modules"), ("space", ".env"), ("space", ".env"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/", ".env"))
    _tree(repo / "node_modules")
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules").exists()
    assert (lane.path / ".env").is_symlink()
    assert context.git.status(lane.path, "main").dirty_count == 0


def test_a_tracked_path_is_never_offered(projects_root: Path, lanes_root: Path) -> None:
    """Discovery only reports ignored paths, and the ignore question is asked with the
    index consulted — so a tracked file can never come back as writable."""
    ui = FakeUi()
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root)
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert ui.asked == []
    assert (lane.path / "file0.txt").read_text() == "content 0\n"


def test_closing_a_lane_with_a_linked_path_leaves_the_target_alone(
    projects_root: Path, lanes_root: Path
) -> None:
    """Being wrong here deletes the main clone's copy, which every other lane shares.
    So it is measured rather than assumed."""
    ui = FakeUi([("space", ".env"), ("space", ".env"), "continue"])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)
    enter_lane.enter(context, lane)
    assert (lane.path / ".env").is_symlink()

    context.git.remove_worktree(repo, lane.path, force=True)

    assert not lane.path.exists()
    assert (repo / ".env").read_text() == "SECRET=1\n"


def test_a_lane_whose_project_moved_is_still_entered(projects_root: Path, lanes_root: Path) -> None:
    """A lane whose metadata points at a repository that has gone still has to open —
    preparation is a convenience and the worktree is the truth."""
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi()
    context = _context(
        ui=ui, projects_root=projects_root, lanes_root=lanes_root, environment=environment
    )
    repo = _project(projects_root)
    lane = _lane(context, repo)
    moved = replace(lane, meta=replace(lane.meta, repo=str(projects_root / "not-here")))

    enter_lane.enter(context, moved)

    assert environment.launched
