"""The picker widget, driven through prompt_toolkit's pipe input.

No terminal is involved. This is the component below the `Ui` seam; session-level
tests replace the whole seam and never reach here.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.output import DummyOutput

from lane.ui.picker import confirm, pick, prompt_text
from lane.ui.seam import Abandoned, Choice


@pytest.fixture
def keys() -> Iterator[PipeInput]:
    with create_pipe_input() as pipe:
        yield pipe


def _options() -> list[Choice[str]]:
    return [
        Choice("open", "open", "Open a new lane"),
        Choice("list", "list", "Show every open lane"),
        Choice("close", "close", "Close a lane"),
    ]


def _pick(keys: PipeInput, sent: str, options: list[Choice[str]] | None = None) -> str:
    keys.send_text(sent)
    return pick(
        "Choose", options if options is not None else _options(), input=keys, output=DummyOutput()
    )


# -- C2: a lone candidate is auto-selected ---------------------------------------


def test_a_lone_candidate_is_returned_without_prompting() -> None:
    """No input is sent at all: if it prompted, this would hang or fail."""
    only = [Choice("the only one", "only")]

    assert pick("Choose", only) == "only"


def test_an_empty_list_is_an_abandonment() -> None:
    with pytest.raises(Abandoned):
        pick("Choose", [])


# -- choosing --------------------------------------------------------------------


def test_enter_chooses_the_first_entry(keys: PipeInput) -> None:
    assert _pick(keys, "\r") == "open"


def test_arrow_keys_move_the_selection(keys: PipeInput) -> None:
    assert _pick(keys, "\x1b[B\r") == "list"


def test_arrows_wrap_around_the_ends(keys: PipeInput) -> None:
    """Up from the first entry lands on the last."""
    assert _pick(keys, "\x1b[A\r") == "close"


def test_home_and_end_jump_to_the_ends(keys: PipeInput) -> None:
    assert _pick(keys, "\x1b[F\r") == "close"


# -- C3: bad input re-prompts rather than aborting -------------------------------


def test_an_unrecognised_key_is_ignored_and_the_picker_stays_up(keys: PipeInput) -> None:
    """The windowed equivalent of the bash picker's re-prompt: never abort."""
    assert _pick(keys, "zx@\r") == "open"


def test_ignored_keys_do_not_disturb_the_selection(keys: PipeInput) -> None:
    assert _pick(keys, "\x1b[Bz\r") == "list"


# -- C4: q, Esc and Ctrl-C all abandon -------------------------------------------


def test_q_is_not_special_and_is_simply_ignored(keys: PipeInput) -> None:
    """Deliberately not an abandon key.

    Only universally understood keys are bound: arrows, Enter, Esc, Ctrl-C. `q`
    meant one rule in a choice prompt and the opposite in a text prompt, which is
    exactly the sort of thing a user should not have to remember.
    """
    assert _pick(keys, "q\r") == "open"


def test_escape_is_not_bound_and_does_nothing(keys: PipeInput) -> None:
    """Going back is the visible Back entry, so Escape need not be bound.

    Binding it made a lone Escape ambiguous with every escape *sequence*, so it took
    over a second to register — which reads as "Esc does not work". Leaving it
    unbound also keeps Option+Arrow out of harm's way.
    """
    assert _pick(keys, "\x1b\r") == "open"


def test_ctrl_c_abandons_rather_than_killing_the_session(keys: PipeInput) -> None:
    with pytest.raises(Abandoned):
        _pick(keys, "\x03")


# -- L1: hints align to a common column -----------------------------------------------


def test_hints_align_to_the_longest_label_width(keys: PipeInput) -> None:
    """Hints start in the same column, determined by the longest label."""
    options = [
        Choice("short", "short", "hint for short"),
        Choice("much longer label", "longer", "hint for longer"),
        Choice("x", "x", "hint for x"),
    ]
    keys.send_text("\r")

    result = pick("Choose", options, input=keys, output=DummyOutput())

    assert result == "short"


def test_a_single_short_label_hint_follows_immediately(keys: PipeInput) -> None:
    """With only one label, its hint is not padded to an arbitrary width."""
    options = [
        Choice("short", "short", "hint here"),
    ]

    assert pick("Choose", options) == "short"


# -- what the user sees ----------------------------------------------------------


def test_the_chosen_value_is_returned_not_the_label(keys: PipeInput) -> None:
    """Actions get a value they can act on, never a string they must re-parse."""
    options = [
        Choice("Feature branch", ("branch", "feature/x")),
        Choice("Detached", ("detached", "")),
    ]
    keys.send_text("\r")

    result = pick("Mode", options, input=keys, output=DummyOutput())

    assert result == ("branch", "feature/x")


# -- C6: confirmation -------------------------------------------------------------


def test_confirm_accepts_y_and_n(keys: PipeInput) -> None:
    """A binary question deserves y/n, not an arrow picker labelled [y/N]."""
    keys.send_text("y")
    assert confirm("Close it?", input=keys, output=DummyOutput()) is True


def test_confirm_n_is_no(keys: PipeInput) -> None:
    keys.send_text("n")
    assert confirm("Close it?", input=keys, output=DummyOutput()) is False


def test_confirm_enter_takes_the_default(keys: PipeInput) -> None:
    keys.send_text("\r")
    assert confirm("Close it?", default=False, input=keys, output=DummyOutput()) is False


def test_confirm_enter_takes_a_true_default(keys: PipeInput) -> None:
    keys.send_text("\r")
    assert confirm("Park them?", default=True, input=keys, output=DummyOutput()) is True


def test_confirm_is_case_insensitive(keys: PipeInput) -> None:
    keys.send_text("Y")
    assert confirm("Close it?", input=keys, output=DummyOutput()) is True


def test_confirm_ignores_unrecognised_keys_rather_than_aborting(keys: PipeInput) -> None:
    keys.send_text("zx3qy")
    assert confirm("Close it?", input=keys, output=DummyOutput()) is True


def test_confirm_ctrl_c_abandons(keys: PipeInput) -> None:
    for key in ("\x03",):
        with create_pipe_input() as pipe:
            pipe.send_text(key)
            with pytest.raises(Abandoned):
                confirm("Close it?", input=pipe, output=DummyOutput())


# -- macOS Option+Arrow, and why Escape must not be eager -------------------------


def test_option_left_does_not_abandon_the_picker(keys: PipeInput) -> None:
    """Option+Left arrives as Escape then Left.

    An eager Escape binding fires on the Escape half and abandons, which is what
    made word movement impossible in text prompts.
    """
    assert _pick(keys, "\x1b[1;3D\r") == "open"


def test_option_right_does_not_abandon_the_picker(keys: PipeInput) -> None:
    assert _pick(keys, "\x1b[1;3C\r") == "open"


# -- the free-text prompt ---------------------------------------------------------


def test_text_returns_what_was_typed(keys: PipeInput) -> None:
    keys.send_text("Fix the export\r")
    assert prompt_text("What are you working on", input=keys, output=DummyOutput()) == (
        "Fix the export"
    )


def test_text_falls_back_to_the_default_when_empty(keys: PipeInput) -> None:
    keys.send_text("\r")
    assert prompt_text("Editor", default="cursor", input=keys, output=DummyOutput()) == "cursor"


def test_q_is_ordinary_input_in_a_text_prompt(keys: PipeInput) -> None:
    """It always was; now it is ordinary everywhere, which is the point."""
    keys.send_text("q\r")
    assert prompt_text("Anything", input=keys, output=DummyOutput()) == "q"


def test_option_left_moves_to_the_start_of_the_word(keys: PipeInput) -> None:
    """The behaviour asked for: Option+Left puts the cursor at the top of the word."""
    keys.send_text("hello world")
    keys.send_text("\x1b[1;3D")  # Option+Left -> start of "world"
    keys.send_text("BIG \r")

    assert prompt_text("Say", input=keys, output=DummyOutput()) == "hello BIG world"


def test_option_left_twice_moves_two_words(keys: PipeInput) -> None:
    keys.send_text("alpha beta gamma")
    keys.send_text("\x1b[1;3D\x1b[1;3D")
    keys.send_text("X\r")

    assert prompt_text("Say", input=keys, output=DummyOutput()) == "alpha Xbeta gamma"


def test_option_right_moves_forward_by_a_word(keys: PipeInput) -> None:
    """Forward lands on the start of the *next* word, which is the standard behaviour."""
    keys.send_text("alpha beta")
    keys.send_text("\x1b[1;3D\x1b[1;3D")  # back to the start of "alpha"
    keys.send_text("\x1b[1;3C")  # forward one word
    keys.send_text("-\r")

    assert prompt_text("Say", input=keys, output=DummyOutput()) == "alpha -beta"


def test_esc_b_and_esc_f_also_move_by_word(keys: PipeInput) -> None:
    """The other encoding some terminals send for Option+Arrow."""
    keys.send_text("one two")
    keys.send_text("\x1bb")  # Meta-b
    keys.send_text("X\r")

    assert prompt_text("Say", input=keys, output=DummyOutput()) == "one Xtwo"


def test_escape_in_a_text_prompt_leaves_word_movement_alone(keys: PipeInput) -> None:
    """Nothing of ours is bound to Escape, so prompt_toolkit keeps its own bindings."""
    keys.send_text("one two")
    keys.send_text("\x1bb")  # Meta-b, the other Option+Left encoding
    keys.send_text("X\r")

    assert prompt_text("Say", input=keys, output=DummyOutput()) == "one Xtwo"


def test_ctrl_c_abandons_a_text_prompt(keys: PipeInput) -> None:
    keys.send_text("\x03")
    with pytest.raises(Abandoned):
        prompt_text("Anything", input=keys, output=DummyOutput())
