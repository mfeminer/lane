"""The session: the menu, and driving a whole working day through it."""

from __future__ import annotations

from pathlib import Path

import pytest

from lane import __version__, session
from lane.actions import ACTIONS, Action
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneStore
from lane.state import StateStore
from tests.conftest import build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


def _context(
    ui: FakeUi,
    projects_root: Path,
    lanes_root: Path,
    *,
    environment: FakeEnvironment | None = None,
    github: StubGitHubClient | None = None,
) -> Context:
    return Context(
        ui=ui,
        git=CliGitBackend(),
        github=github or StubGitHubClient(),
        environment=environment or FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor"),
        config_store=ConfigStore(lanes_root.parent / "cfg"),
        state_store=StateStore(lanes_root.parent / "st"),
    )


# -- D1, D2, D3: the menu --------------------------------------------------------


def test_the_menu_offers_every_action_from_the_table(projects_root: Path, lanes_root: Path) -> None:
    """Generated from one table, so it cannot drift from what lane can do."""
    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if not title:  # the menu, which carries no title of its own
                offered.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    ui = Recording(["quit"])
    session.run(_context(ui, projects_root, lanes_root))

    assert offered == [action.label for action in ACTIONS]
    assert "open" in offered
    assert "quit" in offered


def test_entering_and_closing_are_not_menu_entries(projects_root: Path, lanes_root: Path) -> None:
    """They are the two verbs the listing offers for the row under the cursor.

    Both used to start by asking "which lane?" from a picker showing the same names
    with none of the status — a worse route to the same place. See ADR 0002.
    """
    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if not title:
                offered.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    ui = Recording(["quit"])
    session.run(_context(ui, projects_root, lanes_root))

    assert offered == ["open", "list", "config", "doctor", "quit"]


def test_the_menu_is_always_the_full_list_even_without_git(
    projects_root: Path, lanes_root: Path
) -> None:
    """Prerequisites are enforced where used, never by hiding entries."""
    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if not title:  # the menu, which carries no title of its own
                offered.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    ui = Recording(["quit"])
    environment = FakeEnvironment(tools={})  # no git at all
    context = _context(ui, projects_root, lanes_root, environment=environment)

    session.run(context, git_available=False)

    assert offered == [action.label for action in ACTIONS]


def test_choosing_quit_ends_the_session_cleanly(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi(["quit"])
    assert session.run(_context(ui, projects_root, lanes_root)) == 0


def test_abandoning_the_menu_ends_the_session_cleanly(
    projects_root: Path, lanes_root: Path
) -> None:
    """q, Esc or Ctrl-C at the menu."""
    ui = FakeUi([FakeUi.ABANDON])
    assert session.run(_context(ui, projects_root, lanes_root)) == 0


def test_an_action_returns_to_the_menu_afterwards(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi(["doctor", "quit"])

    assert session.run(_context(ui, projects_root, lanes_root)) == 0
    assert ui.asked.count("") == 2, "the menu was shown again after the action"


# -- D4: abandoning an action returns to the menu --------------------------------


def test_abandoning_an_action_returns_to_the_menu_changing_nothing(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["open", FakeUi.ABANDON, "quit"])
    (projects_root / "a").mkdir()
    git(["init", "--quiet", str(projects_root / "a")])
    git(["init", "--quiet", str(projects_root / "b")])

    assert session.run(_context(ui, projects_root, lanes_root)) == 0
    # Nothing is announced: the menu simply comes back. See test_going_back.py.
    assert not ui.said("left as it was")
    assert not lanes_root.exists()


# -- Ctrl-C while an action is working --------------------------------------------


def _interrupting(label: str) -> Action:
    def run(context: Context) -> None:
        del context
        raise KeyboardInterrupt

    return Action(key=label, label=label, description="raises Ctrl-C", run=run)


def test_ctrl_c_while_an_action_is_working_ends_the_session(
    monkeypatch: pytest.MonkeyPatch, projects_root: Path, lanes_root: Path
) -> None:
    """It used to escape as a traceback; then it was reported and the menu came back.
    Now it does what Ctrl-C does in every persistent terminal program: it leaves."""
    monkeypatch.setattr(session, "ACTIONS", (_interrupting("boom"), *ACTIONS))
    ui = FakeUi(["boom"])

    assert session.run(_context(ui, projects_root, lanes_root)) == 0
    assert ui.said("interrupted")
    assert ui.told[-1].kind == "farewell", "and by the same door quit uses"


def test_an_interruption_says_what_might_be_half_done(
    monkeypatch: pytest.MonkeyPatch, projects_root: Path, lanes_root: Path
) -> None:
    """Unlike backing out of a prompt, this one is not guaranteed to be a no-op:
    the interrupt may have landed in the middle of a step. Saying nothing would
    imply it was clean."""
    monkeypatch.setattr(session, "ACTIONS", (_interrupting("boom"), *ACTIONS))
    ui = FakeUi(["boom"])

    session.run(_context(ui, projects_root, lanes_root))

    assert ui.said("half-done")
    # Named by its current menu name, so the next step is one the user can find.
    assert ui.said("list")


def test_ctrl_c_at_a_prompt_inside_an_action_ends_the_session_silently(
    projects_root: Path, lanes_root: Path
) -> None:
    """The same exit, without the half-done line — because at a prompt nothing is under
    way. Two situations, two exceptions (`Quit` and `KeyboardInterrupt`), one outcome."""
    git(["init", "--quiet", str(projects_root / "a")])
    git(["init", "--quiet", str(projects_root / "b")])
    ui = FakeUi(["open", FakeUi.CTRL_C])

    assert session.run(_context(ui, projects_root, lanes_root)) == 0
    assert ui.told[-1].kind == "farewell"
    assert not ui.said("half-done"), "nothing was under way, so nothing may be half-done"
    assert not lanes_root.exists()


def test_ctrl_c_at_the_bare_menu_prompt_still_ends_the_session(
    projects_root: Path, lanes_root: Path
) -> None:
    """It already did, by a different route. Pinned so a later change cannot quietly
    turn the menu's Ctrl-C back into "show the menu again"."""
    ui = FakeUi([FakeUi.CTRL_C])

    assert session.run(_context(ui, projects_root, lanes_root)) == 0
    assert ui.told[-1].kind == "farewell"


def test_ctrl_c_in_the_preparation_checklist_ends_the_session(
    projects_root: Path, lanes_root: Path
) -> None:
    """Not "back to the menu with the lane unprepared" — out. Nothing is written and no
    editor opens, exactly as `discard` leaves things; what differs is where you land."""
    _origin, clone = build_repo(projects_root / "_b", default_branch="main")
    repo = projects_root / "thing"
    clone.rename(repo)
    (repo / ".gitignore").write_text("node_modules/\n")
    git(["add", ".gitignore"], cwd=repo)
    git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
    git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg").write_text("from the main clone\n")

    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi(
        [
            "open",
            "thing",
            "new work",
            "Fix the CSV export",
            "branch",
            "bugfix/fix-the-csv-export",
            FakeUi.CTRL_C,
        ]
    )
    context = _context(ui, projects_root, lanes_root, environment=environment)

    assert session.run(context) == 0
    assert ui.told[-1].kind == "farewell"
    assert context.prepare_store().load().steps == ()
    assert environment.launched == []


# -- D7: without git, everything but doctor refuses -------------------------------


def test_without_git_the_session_still_starts_and_says_why(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["quit"])
    context = _context(ui, projects_root, lanes_root, environment=FakeEnvironment(tools={}))

    session.run(context, git_available=False)

    assert ui.said("git is not installed")
    assert ui.said("doctor")


def test_without_git_doctor_is_still_reachable(projects_root: Path, lanes_root: Path) -> None:
    """Doctor explains missing prerequisites, so it can never sit behind one."""
    ui = FakeUi(["doctor", "quit"])
    context = _context(ui, projects_root, lanes_root, environment=FakeEnvironment(tools={}))

    session.run(context, git_available=False)

    assert ui.said("lane doctor")
    assert ui.said("git is not installed")


def test_without_git_opening_a_lane_is_refused_with_a_reason(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["open", "quit"])
    context = _context(ui, projects_root, lanes_root, environment=FakeEnvironment(tools={}))

    session.run(context, git_available=False)

    assert ui.said("needs git")


def test_without_git_the_session_heading_still_names_the_version(
    projects_root: Path, lanes_root: Path
) -> None:
    """Which copy is running is the first thing to establish when nothing works."""
    ui = FakeUi(["quit"])
    context = _context(ui, projects_root, lanes_root, environment=FakeEnvironment(tools={}))

    session.run(context, git_available=False)

    assert ui.said(__version__)


# -- I30: end to end -------------------------------------------------------------


def test_a_whole_working_day_menu_open_menu_close_menu_quit(
    projects_root: Path, lanes_root: Path
) -> None:
    """menu → open a lane → menu → lanes → close it → menu → quit, asserting the git state.

    Closing is reached through the listing now, with the cursor on the lane, so the
    day has one menu entry fewer in it than it used to.
    """
    _origin, clone = build_repo(projects_root / "_b", default_branch="main")
    repo = projects_root / "thing"
    clone.rename(repo)

    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi(
        [
            # menu -> open
            "open",
            "thing",  # project
            "new work",  # not a branch that already exists
            "Fix the CSV export",  # description
            "branch",  # mode
            "bugfix/fix-the-csv-export",  # branch
            # menu -> list -> the row -> close it
            "list",
            "fix-the-csv-export",  # the row under the cursor
            "close",  # what to do with it
            [],  # the close screen, accepted as it opened
            # The listing has nothing left to show, so it lands back at the menu.
            "quit",
        ]
    )
    context = _context(
        ui,
        projects_root,
        lanes_root,
        environment=environment,
        github=StubGitHubClient(),
    )

    exit_code = session.run(context)

    assert exit_code == 0
    assert ui.unanswered() == 0, "the whole script was consumed"

    backend = CliGitBackend()
    lane_path = lanes_root / "thing" / "fix-the-csv-export"
    # The worktree is gone, git knows it is gone, and the branch went with it.
    assert not lane_path.exists()
    assert str(lane_path) not in git(["worktree", "list", "--porcelain"], cwd=repo)
    assert not backend.branch_exists(repo, "bugfix/fix-the-csv-export")
    assert LaneStore(lanes_root).list_lanes() == []
    # The editor was launched exactly once, into the lane.
    assert environment.launched == [("cursor", lane_path)]
    # And the repository itself is untouched and clean.
    assert backend.status(repo, "main").dirty_count == 0


def test_two_lanes_run_side_by_side_without_colliding(
    projects_root: Path, lanes_root: Path
) -> None:
    """The whole point of the tool."""
    _origin, clone = build_repo(projects_root / "_b", default_branch="main")
    repo = projects_root / "thing"
    clone.rename(repo)

    ui = FakeUi(
        [
            "open",
            "thing",
            "new work",
            "First job",
            "branch",
            "feature/first-job",
            "open",
            "thing",
            "new work",
            "Second job",
            "branch",
            "bugfix/second-job",
            "quit",
        ]
    )
    session.run(_context(ui, projects_root, lanes_root))

    backend = CliGitBackend()
    first = lanes_root / "thing" / "first-job"
    second = lanes_root / "thing" / "second-job"
    assert first.is_dir()
    assert second.is_dir()
    assert backend.status(first, "main").branch == "feature/first-job"
    assert backend.status(second, "main").branch == "bugfix/second-job"
    # Neither lane tracks anything, so a bare push in either cannot reach main.
    assert backend.status(first, "main").upstream is None
    assert backend.status(second, "main").upstream is None


def test_discarding_the_preparation_screen_leaves_the_lane_exactly_as_it_was(
    projects_root: Path, lanes_root: Path
) -> None:
    """`discard` unwinds the whole way, and every step of that is worth pinning now that
    it is a named row rather than an accident of Ctrl-C's plumbing.

    `Abandoned` out of `_prepare` skips `_launch` entirely, and the session catches it and
    shows the menu again. Nothing is written, no editor opens, and what is left behind is
    a complete lane that is merely unprepared — which the listing describes and the next
    enter repairs.
    """
    _origin, clone = build_repo(projects_root / "_b", default_branch="main")
    repo = projects_root / "thing"
    clone.rename(repo)
    (repo / ".gitignore").write_text("node_modules/\n")
    git(["add", ".gitignore"], cwd=repo)
    git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
    git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg").write_text("from the main clone\n")

    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi(
        [
            "open",
            "thing",
            "new work",
            "Fix the CSV export",
            "branch",
            "bugfix/fix-the-csv-export",
            FakeUi.ABANDON,  # `discard`, which is what the row does
            "quit",
        ]
    )
    context = _context(ui, projects_root, lanes_root, environment=environment)
    lane_path = lanes_root / "thing" / "fix-the-csv-export"

    assert session.run(context) == 0
    assert ui.unanswered() == 0, "the menu came back and took the next answer"

    assert lane_path.is_dir(), "a complete lane, merely unprepared"
    assert not (lane_path / "node_modules").exists()
    assert context.prepare_store().load().steps == ()
    assert environment.launched == [], "the editor is on the other side of preparation"


# -- The road: the session opens on it and closes it ------------------------------


def test_the_session_opens_with_the_splash(projects_root: Path, lanes_root: Path) -> None:
    """The road is laid before the menu is offered, once, and it names the version."""
    ui = FakeUi(["quit"])

    session.run(_context(ui, projects_root, lanes_root))

    splashes = [told for told in ui.told if told.kind == "splash"]
    assert len(splashes) == 1
    assert __version__ in splashes[0].text
    assert ui.told[0].kind == "splash"


def test_quitting_closes_the_road(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi(["quit"])

    session.run(_context(ui, projects_root, lanes_root))

    assert ui.told[-1].kind == "farewell"


def test_backing_out_of_the_menu_closes_the_road_too(projects_root: Path, lanes_root: Path) -> None:
    """Ctrl-C at the menu ends the session, so it leaves by the same door as quit."""
    ui = FakeUi([FakeUi.ABANDON])

    session.run(_context(ui, projects_root, lanes_root))

    assert ui.told[-1].kind == "farewell"


def test_a_whole_working_day_with_a_lane_that_needs_preparing(
    projects_root: Path, lanes_root: Path
) -> None:
    """The same day, in a project that keeps something outside git.

    The point of the whole feature in one script: asked once on the way in, asked
    **nothing** on the way back in, and the close is unaffected because the copied path is
    ignored and so never looked dirty.
    """
    _origin, clone = build_repo(projects_root / "_b", default_branch="main")
    repo = projects_root / "thing"
    clone.rename(repo)
    (repo / ".gitignore").write_text("node_modules/\n")
    git(["add", ".gitignore"], cwd=repo)
    git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
    git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg").write_text("from the main clone\n")

    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi(
        [
            # menu -> open, which ends by entering, which prepares
            "open",
            "thing",
            "new work",
            "Fix the CSV export",
            "branch",
            "bugfix/fix-the-csv-export",
            ["node_modules"],  # one keystroke: it comes in
            # menu -> list -> enter it again. Nothing is asked this time.
            "list",
            "fix-the-csv-export",
            "enter",
            # menu -> list -> close it
            "list",
            "fix-the-csv-export",
            "close",
            [],
            "quit",
        ]
    )
    context = _context(ui, projects_root, lanes_root, environment=environment)
    lane_path = lanes_root / "thing" / "fix-the-csv-export"

    exit_code = session.run(context)

    assert exit_code == 0
    assert ui.unanswered() == 0, "the whole script was consumed — nothing extra was asked"
    assert environment.launched == [("cursor", lane_path), ("cursor", lane_path)]
    assert not lane_path.exists(), "the lane closed cleanly, copied tree and all"
    assert (repo / "node_modules" / "pkg").read_text() == "from the main clone\n"
