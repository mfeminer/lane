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

    assert offered == ["open", "lanes", "settings", "doctor", "quit"]


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


def test_ctrl_c_while_an_action_is_working_returns_to_the_menu(
    monkeypatch: pytest.MonkeyPatch, projects_root: Path, lanes_root: Path
) -> None:
    """Inside a prompt Ctrl-C is bound and backs out. Outside one — while a step is
    actually running — it used to escape as a traceback, killing the session."""
    monkeypatch.setattr(session, "ACTIONS", (_interrupting("boom"), *ACTIONS))
    ui = FakeUi(["boom", "quit"])

    assert session.run(_context(ui, projects_root, lanes_root)) == 0
    assert ui.said("interrupted")


def test_an_interruption_says_what_might_be_half_done(
    monkeypatch: pytest.MonkeyPatch, projects_root: Path, lanes_root: Path
) -> None:
    """Unlike backing out of a prompt, this one is not guaranteed to be a no-op:
    the interrupt may have landed in the middle of a step. Saying nothing would
    imply it was clean."""
    monkeypatch.setattr(session, "ACTIONS", (_interrupting("boom"), *ACTIONS))
    ui = FakeUi(["boom", "quit"])

    session.run(_context(ui, projects_root, lanes_root))

    assert ui.said("half-done")
    # Named by its current menu name, so the next step is one the user can find.
    assert ui.said("lanes")


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
            "Fix the CSV export",  # description
            "branch",  # mode
            "bugfix/fix-the-csv-export",  # branch
            # menu -> lanes -> the row -> close it
            "lanes",
            "fix-the-csv-export",  # the row under the cursor
            "close",  # what to do with it
            True,  # confirm the close
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
            "First job",
            "branch",
            "feature/first-job",
            "open",
            "thing",
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
