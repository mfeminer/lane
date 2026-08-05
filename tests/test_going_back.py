"""Going back is an option you can see, not a key you have to know.

Every prompt that offers choices ends with a visible "Back" entry. Esc and Ctrl-C
still work for people who reach for them, but nothing requires knowing that.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.output import DummyOutput

from lane import session
from lane.actions import ACTIONS
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.state import StateStore
from lane.ui.console_ui import ConsoleUi
from lane.ui.picker import ESCAPE_TIMEOUT
from lane.ui.seam import Abandoned, Cell, Choice, Column, Row
from tests.conftest import git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


@pytest.fixture
def keys() -> Iterator[PipeInput]:
    with create_pipe_input() as pipe:
        yield pipe


def _context(ui: FakeUi, projects_root: Path, lanes_root: Path) -> Context:
    return Context(
        ui=ui,
        git=CliGitBackend(),
        github=StubGitHubClient(),
        environment=FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor"),
        config_store=ConfigStore(lanes_root.parent / "cfg"),
        state_store=StateStore(lanes_root.parent / "st"),
    )


# -- the visible way back --------------------------------------------------------


def test_a_choice_prompt_offers_a_visible_back_entry(keys: PipeInput) -> None:
    """Down to the last entry, which is Back, then Enter."""
    ui = ConsoleUi()
    keys.send_text("\x1b[B\x1b[B\r")

    with pytest.raises(Abandoned):
        ui.choose(
            "Pick one",
            [Choice("first", "a"), Choice("second", "b")],
            input=keys,
            output=DummyOutput(),
        )


def test_the_back_entry_is_labelled_so_it_reads_as_an_action(keys: PipeInput) -> None:
    seen: list[str] = []
    ui = ConsoleUi()
    keys.send_text("\r")

    ui.choose(
        "Pick one",
        [Choice("first", "a"), Choice("second", "b")],
        input=keys,
        output=DummyOutput(),
        on_render=seen.append,
    )

    assert any("back" in label.lower() for label in seen), seen


def test_choosing_a_real_option_still_returns_it(keys: PipeInput) -> None:
    ui = ConsoleUi()
    keys.send_text("\r")

    result = ui.choose(
        "Pick one",
        [Choice("first", "a"), Choice("second", "b")],
        input=keys,
        output=DummyOutput(),
    )

    assert result == "a"


def test_a_prompt_can_opt_out_of_the_back_entry(keys: PipeInput) -> None:
    """The menu already has `quit`, and the listing already has its own way back."""
    seen: list[str] = []
    ui = ConsoleUi()
    keys.send_text("\r")

    ui.choose(
        "Pick one",
        [Choice("first", "a"), Choice("second", "b")],
        input=keys,
        output=DummyOutput(),
        back=None,
        on_render=seen.append,
    )

    assert not any("back" in label.lower() for label in seen), seen


def test_a_lone_option_still_auto_selects_despite_the_back_entry(keys: PipeInput) -> None:
    """Adding "Back" must not turn a one-candidate prompt into a question."""
    ui = ConsoleUi()

    result = ui.choose(
        "Pick one", [Choice("the only one", "only")], input=keys, output=DummyOutput()
    )

    assert result == "only"


def test_a_browsed_table_ends_with_a_visible_back_row(keys: PipeInput) -> None:
    """The listing is a screen, so its way out is a row you can see, not a key."""
    seen: list[str] = []
    ui = ConsoleUi()
    keys.send_text("\r")

    ui.browse(
        "2 open lanes",
        [Column("lane"), Column("state")],
        lambda: [
            Row(value="a", cells=(Cell("first"), Cell("no commits yet"))),
            Row(value="b", cells=(Cell("second"), Cell("● 1 uncommitted"))),
        ],
        input=keys,
        output=DummyOutput(),
        on_render=seen.append,
    )

    assert any("back" in line.lower() for line in seen), seen


def test_choosing_the_back_row_of_a_table_abandons(keys: PipeInput) -> None:
    ui = ConsoleUi()
    keys.send_text("\x1b[F\r")  # End, which lands on Back

    with pytest.raises(Abandoned):
        ui.browse(
            "2 open lanes",
            [Column("lane")],
            lambda: [
                Row(value="a", cells=(Cell("first"),)),
                Row(value="b", cells=(Cell("second"),)),
            ],
            input=keys,
            output=DummyOutput(),
        )


# -- the menu keeps `quit` rather than gaining a second way out -------------------


def test_the_menu_has_quit_and_not_a_duplicate_back(projects_root: Path, lanes_root: Path) -> None:
    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, *, back="Back", on_render=None):  # type: ignore[no-untyped-def]
            if not title:
                offered.extend(o.label for o in options)
            return super().choose(title, options, back=back, on_render=on_render)

    ui = Recording(["quit"])
    session.run(_context(ui, projects_root, lanes_root))

    assert offered == [action.label for action in ACTIONS]
    assert offered.count("quit") == 1
    assert not any("back" in label.lower() for label in offered)


# -- Escape must not feel broken --------------------------------------------------


def test_the_escape_sequence_timeout_stays_short() -> None:
    """A stray Escape must not leave the prompt feeling stuck.

    Escape is not bound to anything — going back is the visible entry — but the
    parser still waits this long to see whether a sequence follows, and
    prompt_toolkit's 0.5s default was noticeable.
    """
    assert ESCAPE_TIMEOUT <= 0.1


def test_ctrl_c_still_backs_out_of_a_choice_prompt(keys: PipeInput) -> None:
    """Not required either, but every terminal user reaches for it."""
    ui = ConsoleUi()
    keys.send_text("\x03")

    with pytest.raises(Abandoned):
        ui.choose(
            "Pick one",
            [Choice("first", "a"), Choice("second", "b")],
            input=keys,
            output=DummyOutput(),
        )


# -- backing out says nothing ----------------------------------------------------


def test_backing_out_of_an_action_returns_to_the_menu_without_commentary(
    projects_root: Path, lanes_root: Path
) -> None:
    """ "Left as it was." explained nothing. Other tools just show the menu again."""
    git(["init", "--quiet", str(projects_root / "a")])
    git(["init", "--quiet", str(projects_root / "b")])
    ui = FakeUi(["open", FakeUi.ABANDON, "quit"])

    session.run(_context(ui, projects_root, lanes_root))

    assert not ui.said("left as it was")
    assert not ui.said("abandoned")
    assert not ui.said("cancelled")


# -- L3: text and confirm prompts show how to back out ----


def test_a_text_prompt_shows_how_to_back_out(keys: PipeInput) -> None:
    """A free-text prompt renders a dim footer naming the one way out."""
    seen: list[str] = []
    ui = ConsoleUi()
    keys.send_text("test answer\r")

    ui.text(
        "What are you working on",
        input=keys,
        output=DummyOutput(),
        on_render=seen.append,
    )

    assert any("ctrl-c" in line.lower() for line in seen), seen


def test_a_confirm_prompt_shows_how_to_back_out(keys: PipeInput) -> None:
    """A yes/no prompt renders a dim footer naming the one way out."""
    seen: list[str] = []
    ui = ConsoleUi()
    keys.send_text("y")

    ui.confirm(
        "Close it?",
        input=keys,
        output=DummyOutput(),
        on_render=seen.append,
    )

    assert any("ctrl-c" in line.lower() for line in seen), seen
