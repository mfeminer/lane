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
    ui = FakeUi([[]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/", ".env"))
    _tree(repo / "node_modules")
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("node_modules" in row for row in rows)
    assert any(".env" in row for row in rows)
    assert len(ui.asked) == 1, "one screen, not a queue of questions"


def test_every_row_starts_out_and_accepting_writes_nothing_in(
    projects_root: Path, lanes_root: Path
) -> None:
    """The untouched answer has to be the one that changes nothing: one Enter records
    every visible answer, including the rows nobody ticked."""
    ui = FakeUi([[]])
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
    ui = FakeUi([[]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")

    enter_lane.enter(context, _lane(context, repo))

    assert ui.said("Answers are remembered per project")


def test_ticking_a_row_brings_the_path_in_and_remembers_it(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([["node_modules"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "pkg")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules" / "pkg").read_text() == "pkg\n"
    assert [(s.path, s.verb) for s in context.prepare_store().load().for_project("demo")] == [
        ("node_modules", Verb.CLONE)
    ]


def test_a_dozen_paths_are_a_dozen_keystrokes_and_one_screen(
    projects_root: Path, lanes_root: Path
) -> None:
    """The complaint this screen was rebuilt for: changing an answer used to mean going
    into the path and back out again, once per path."""
    ui = FakeUi([[f"pkg{n}/node_modules" for n in range(12)]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    for n in range(12):
        (repo / f"pkg{n}").mkdir()
        (repo / f"pkg{n}" / "main.py").write_text("tracked\n")
        _tree(repo / f"pkg{n}" / "node_modules", "pkg")
    git(["add", "-A"], cwd=repo)
    git(["commit", "--quiet", "-m", "packages"], cwd=repo)
    git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert len(ui.asked) == 1, "one screen, and no sub-screen under it"
    assert all((lane.path / f"pkg{n}/node_modules/pkg").exists() for n in range(12))


def test_a_second_lane_in_the_same_project_asks_nothing(
    projects_root: Path, lanes_root: Path
) -> None:
    """The whole point of remembering: this is the screen's second appearance, and it
    does not appear."""
    first_ui = FakeUi([["node_modules"]])
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


def test_ticking_twice_leaves_the_path_out(projects_root: Path, lanes_root: Path) -> None:
    """Two answers and only two — there is no third press to get lost in."""
    ui = FakeUi([[".env", ".env"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert [s.verb for s in context.prepare_store().load().for_project("demo")] == [Verb.SKIP]
    assert not (lane.path / ".env").exists()


def test_a_ticked_path_already_in_the_lane_is_left_alone(
    projects_root: Path, lanes_root: Path
) -> None:
    """The one rule the checkbox cannot carry, so it is stated once and holds always:
    a tick never overwrites what the lane already has. Anything else silently destroys
    work done inside the lane."""
    ui = FakeUi([["node_modules"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "fresh")
    lane = _lane(context, repo)
    _tree(lane.path / "node_modules", "mine")

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules" / "mine").exists(), "the lane's own copy survives"
    assert not (lane.path / "node_modules" / "fresh").exists()
    assert not any(told.kind == "progress" for told in ui.told), "and nothing was done"


def test_a_path_already_in_the_lane_says_so_on_its_row(
    projects_root: Path, lanes_root: Path
) -> None:
    """A tick that does nothing has to look different from one that does, or the row is
    lying about what accepting the screen will do."""
    ui = FakeUi([[]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules", "fresh")
    lane = _lane(context, repo)
    _tree(lane.path / "node_modules", "mine")

    enter_lane.enter(context, lane)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("already there" in row for row in rows)


def test_the_running_total_says_what_is_about_to_be_copied(
    projects_root: Path, lanes_root: Path
) -> None:
    """Forty rows do not fit on a screen, so the one line saying what you have decided —
    and what it costs — has to be somewhere you are already looking."""
    ui = FakeUi([["node_modules"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "big").write_bytes(b"\0" * 300_000)

    enter_lane.enter(context, _lane(context, repo))

    said = [told.text for told in ui.told if told.kind == "summary"]
    assert said and said[-1].endswith("coming in"), said
    assert "KB" in said[-1]


def test_sizes_arrive_after_the_rows_do(projects_root: Path, lanes_root: Path) -> None:
    """`du` on a large tree is slow, so the rows are complete first and the sizes fill in
    behind — the lanes table's own shape, and its own `fill`."""
    ui = FakeUi([[]])
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
    ui = FakeUi([[]])
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


def test_bringing_in_a_path_that_looks_like_secrets_says_every_lane_gets_a_copy(
    projects_root: Path, lanes_root: Path
) -> None:
    """Copying a `.env` into every lane multiplies the number of places a secret lives.
    Closing the lane removes them — a refused close does not."""
    ui = FakeUi([[".env"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")

    enter_lane.enter(context, _lane(context, repo))

    assert ui.said("looks like it holds secrets")
    assert ui.said("every lane")


def test_a_path_that_does_not_look_like_secrets_says_nothing_about_them(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([["node_modules"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/",))
    _tree(repo / "node_modules")

    enter_lane.enter(context, _lane(context, repo))

    assert not ui.said("secrets")


# -- what preparation must not disturb --------------------------------------------


def test_a_prepared_lane_is_still_clean_to_git(projects_root: Path, lanes_root: Path) -> None:
    """Only paths git ignores in the lane are ever written, which is what keeps
    preparation out of the listing's `state` cell and out of the close flow's checks."""
    ui = FakeUi([["node_modules", ".env"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("node_modules/", ".env"))
    _tree(repo / "node_modules")
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    assert (lane.path / "node_modules").exists()
    assert (lane.path / ".env").exists()
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


def test_closing_a_lane_leaves_the_main_clones_copy_alone(
    projects_root: Path, lanes_root: Path
) -> None:
    """Being wrong here deletes the main clone's copy, which every other lane is made
    from. So it is measured rather than assumed."""
    ui = FakeUi([[".env"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=(".env",))
    (repo / ".env").write_text("SECRET=1\n")
    lane = _lane(context, repo)
    enter_lane.enter(context, lane)
    assert (lane.path / ".env").exists()

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


# -- a folder of loose ignored files ----------------------------------------------


def _litter(repo: Path, directory: str, *names: str) -> Path:
    """Ignored files in a directory that also holds tracked work.

    The tracked file is the whole point: without it git collapses the directory to one
    ignored row and there is nothing to group. One tracked file and every ignored file
    inside is reported separately — which is how a real repository reached 55 rows.

    Returns the tracked file, committed and pushed so the lane has it too.
    """
    (repo / directory).mkdir(parents=True, exist_ok=True)
    for name in names:
        (repo / directory / name).write_text(f"{name}\n")

    tracked = repo / directory / "tracked.md"
    tracked.write_text("tracked\n")
    git(["add", f"{directory}/tracked.md"], cwd=repo)
    git(["commit", "--quiet", "-m", f"tracked file in {directory}"], cwd=repo)
    git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    return tracked


def test_a_folder_of_loose_ignored_files_is_one_row_not_forty(
    projects_root: Path, lanes_root: Path
) -> None:
    """The whole point: a directory git could not collapse must not become forty rows on
    the way to the editor."""
    ui = FakeUi([[]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("*.log",))
    _litter(repo, "logs", *[f"day{n}.log" for n in range(1, 41)])

    enter_lane.enter(context, _lane(context, repo))

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert len(rows) == 1, f"one row, not forty: {rows}"
    assert any("logs/ · 40 ignored paths" in row for row in rows)


def test_one_keystroke_on_a_folder_brings_in_every_path_inside_it(
    projects_root: Path, lanes_root: Path
) -> None:
    """A folder row stands for everything beneath it: one keystroke answers the lot,
    which is the whole reason nobody has to descend into fourteen packages one at a
    time."""
    ui = FakeUi([["logs/ · 3 ignored paths"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("*.log",))
    _litter(repo, "logs", "a.log", "b.log", "c.log")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    for name in ("a.log", "b.log", "c.log"):
        assert (lane.path / "logs" / name).exists(), name
    assert [(s.path, s.verb) for s in context.prepare_store().load().for_project("demo")] == [
        ("logs/a.log", Verb.CLONE),
        ("logs/b.log", Verb.CLONE),
        ("logs/c.log", Verb.CLONE),
    ], "one step per path — a folder is never a step for its directory"


def test_a_folder_answer_never_writes_the_directory_itself(
    projects_root: Path, lanes_root: Path
) -> None:
    """The directory is only *partly* ignored — that is why its files were listed one by
    one — so it holds tracked work too. Cloning the directory would overwrite it."""
    ui = FakeUi([["logs/ · 3 ignored paths"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("*.log",))
    _litter(repo, "logs", "a.log", "b.log", "c.log")
    lane = _lane(context, repo)
    (lane.path / "logs" / "tracked.md").write_text("the lane's own version\n")

    enter_lane.enter(context, lane)

    assert (lane.path / "logs" / "tracked.md").read_text() == "the lane's own version\n"
    assert context.git.status(lane.path, "main").dirty_count == 1, "only the file it edited"


def test_a_deep_tree_opens_on_its_branching_points_not_on_its_leaves(
    projects_root: Path, lanes_root: Path
) -> None:
    """The complaint this shape answers: two hundred ignored paths scattered under
    different packages must not be two hundred rows to choose between."""
    ui = FakeUi([[]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("*.log", ".env"))
    for name in ("api", "web", "console"):
        _litter(repo, f"packages/{name}", ".env", "a.log", "b.log")

    enter_lane.enter(context, _lane(context, repo))

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert len(rows) == 1, f"one row to open, not nine: {rows}"
    assert rows[0].startswith("packages/ · 9 ignored paths")
    inside = [told.text for told in ui.told if told.kind == "nested"]
    assert any("packages/api/ · 3 ignored paths" in row for row in inside), (
        "and the level below it is the packages, not their files"
    )


def test_one_keystroke_at_the_top_of_a_tree_answers_every_leaf_under_it(
    projects_root: Path, lanes_root: Path
) -> None:
    """A folder is presentation at every depth: answering the top of the tree stores one
    step per path and never one for a directory."""
    ui = FakeUi([["packages/ · 9 ignored paths"]])
    context = _context(ui=ui, projects_root=projects_root, lanes_root=lanes_root)
    repo = _project(projects_root, ignore=("*.log", ".env"))
    for name in ("api", "web", "console"):
        _litter(repo, f"packages/{name}", ".env", "a.log", "b.log")
    lane = _lane(context, repo)

    enter_lane.enter(context, lane)

    steps = context.prepare_store().load().for_project("demo")
    assert len(steps) == 9
    assert all(step.verb is Verb.CLONE for step in steps)
    assert all(step.path.count("/") == 2 for step in steps), "never a step for a directory"
    assert (lane.path / "packages" / "api" / ".env").exists()
