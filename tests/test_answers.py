"""`Prefilled`: the seam that lets a flag answer a prompt.

The whole point of this object is that there is **one** code path. A subcommand
does not reimplement what `open_lane._gather` or `close_lane._ask` decides; it
answers those decisions in advance, and anything it did not answer either falls
through to the real prompt (a terminal is there) or is refused by name (one is
not). Nothing here knows what a lane is.
"""

from __future__ import annotations

import pytest

from lane.cli.answers import NeedsAnswer, NoSuchOption, Prefilled
from lane.ui.seam import Cell, Choice, Column, Node, Row
from tests.fakes import FakeUi


def test_a_supplied_answer_satisfies_a_choose_without_asking() -> None:
    """The flag was given, so the question is not asked — anywhere, TTY or not."""
    ui = Prefilled({"project": "acme"}, FakeUi(), interactive=False)

    chosen = ui.choose(
        "Which project?",
        [Choice("acme", "acme-value"), Choice("other", "other-value")],
        key="project",
    )

    assert chosen == "acme-value"


def test_a_prompt_nothing_answered_and_no_terminal_is_refused_by_name() -> None:
    """Never a hang: a question nothing can answer is named, with its flag."""
    ui = Prefilled({}, FakeUi(), interactive=False, flags={"project": "--project"})

    with pytest.raises(NeedsAnswer) as raised:
        ui.choose("Which project?", [Choice("acme", "acme-value")], key="project")

    assert raised.value.flag == "--project"
    assert "Which project?" in str(raised.value)


def test_a_supplied_answer_that_matches_nothing_is_refused_with_what_was_offered() -> None:
    """A wrong flag value is not a missing one: it names what it could have been."""
    ui = Prefilled(
        {"project": "nosuch"}, FakeUi(), interactive=False, flags={"project": "--project"}
    )

    with pytest.raises(NoSuchOption) as raised:
        ui.choose("Which project?", [Choice("acme", 1), Choice("widgets", 2)], key="project")

    assert raised.value.flag == "--project"
    assert "nosuch" in str(raised.value)
    assert "acme" in str(raised.value)
    assert "widgets" in str(raised.value)


def test_a_wrong_value_is_refused_even_when_a_terminal_is_there() -> None:
    """It must never fall through to the prompt: the user said what they wanted,
    and quietly asking again would answer a different question from the one asked."""
    asked = FakeUi(["acme"])
    ui = Prefilled({"project": "nosuch"}, asked, interactive=True, flags={"project": "--project"})

    with pytest.raises(NoSuchOption):
        ui.choose("Which project?", [Choice("acme", 1)], key="project")

    assert asked.asked == []


def test_an_unanswered_prompt_is_asked_for_real_when_a_terminal_is_there() -> None:
    """Missing input is TTY-gated: with a terminal, the interactive prompt is the
    fallback — same wording, same validation, same re-ask loop. No second flow."""
    asked = FakeUi(["widgets"])
    ui = Prefilled({}, asked, interactive=True)

    chosen = ui.choose("Which project?", [Choice("acme", 1), Choice("widgets", 2)], key="project")

    assert chosen == 2
    assert asked.asked == ["Which project?"]


def test_what_an_action_says_reaches_the_real_ui_even_when_nothing_can_be_asked() -> None:
    """Telling is not input. A refusal, a spinner and a `✓` happen in a pipe too —
    routed to stderr by the caller, which is what keeps stdout parseable."""
    told = FakeUi()
    ui = Prefilled({}, told, interactive=False)

    ui.ok("Lane open: demo/x")
    ui.detail("  /lanes/demo/x")
    ran = ui.progress("Fetching origin…", lambda: "fetched")

    assert ran == "fetched"
    assert told.said("Lane open: demo/x")
    assert told.said("Fetching origin…")


def test_a_supplied_value_answers_a_text_prompt_and_a_missing_one_is_named() -> None:
    ui = Prefilled({"description": "fix the pager"}, FakeUi(), interactive=False)

    assert ui.text("What are you working on", key="description") == "fix the pager"

    with pytest.raises(NeedsAnswer):
        ui.text("Lane name", key="lane-name")


def test_a_supplied_answer_answers_a_confirm_and_a_missing_one_is_named() -> None:
    ui = Prefilled({"enter-that-lane": True}, FakeUi(), interactive=False)

    assert ui.confirm("Enter that lane instead?", key="enter-that-lane") is True

    with pytest.raises(NeedsAnswer):
        ui.confirm("Close it?", key="proceed")


def test_a_supplied_answer_picks_a_row_of_a_browse_by_any_of_its_cells() -> None:
    """`--branch feature/two` names a row of the branch table the same way a test
    script does: by what is written on it. A table is not a list of flag values."""
    rows = [
        Row(value="one", cells=(Cell("feature/one"), Cell("origin only"))),
        Row(value="two", cells=(Cell("feature/two"), Cell(""))),
    ]
    ui = Prefilled({"branch": "feature/two"}, FakeUi(), interactive=False)

    chosen, index = ui.browse("2 branches in demo", (Column("branch"),), lambda: rows, key="branch")

    assert chosen == "two"
    assert index == 1


def test_a_browse_answer_matching_no_row_is_refused_and_names_some_of_them() -> None:
    rows = [Row(value="one", cells=(Cell("feature/one"),))]
    ui = Prefilled({"branch": "nope"}, FakeUi(), interactive=False, flags={"branch": "--branch"})

    with pytest.raises(NoSuchOption) as raised:
        ui.browse("1 branch in demo", (Column("branch"),), lambda: rows, key="branch")

    assert raised.value.flag == "--branch"
    assert "feature/one" in str(raised.value)


def test_a_supplied_decision_answers_a_check_from_the_rows_it_is_offered() -> None:
    """The close screen's rows are not known until it is built — which branches a
    lane abandoned is a fact about that lane. So the answer is a decision *taken
    against the rows*, not a value written out in advance: `--delete-others` can
    only be checked against a set that exists at that moment."""
    nodes = [
        Node(row=Row(value="rescue", cells=(Cell("park those commits on wip/x"),))),
        Node(row=Row(value="delete", cells=(Cell("delete branch feature/x"),))),
    ]
    seen: list[str] = []

    def decide(offered: object, defaults: object) -> dict[str, bool]:
        assert isinstance(offered, list)
        assert isinstance(defaults, dict)
        seen.extend(node.row.value for node in offered)
        return {**defaults, "delete": True}

    ui = Prefilled({"close": decide}, FakeUi(), interactive=False)

    answered = ui.check(
        "Closing demo/x",
        (Column("what closing does"),),
        lambda: nodes,
        answers={"rescue": True},
        key="close",
    )

    assert answered == {"rescue": True, "delete": True}
    assert seen == ["rescue", "delete"]


def test_a_check_with_nothing_supplied_and_no_terminal_is_refused() -> None:
    """Entering a lane with an unanswered ignored path lands here, and refusing is
    the whole point: including it silently copies what nobody asked for, and
    skipping it silently exits 0 on a lane that is not ready."""
    ui = Prefilled({}, FakeUi(), interactive=False)

    with pytest.raises(NeedsAnswer):
        ui.check("3 paths lane has not been told about", (), lambda: [], key="preparation")


def test_a_supplied_answer_is_used_once_and_a_re_ask_says_it_was_not_accepted() -> None:
    """Several prompts in lane re-ask when the answer will not do — a branch name git
    rejects, a lane name already taken, a branch another lane is holding. Replaying
    the same flag into the same prompt would loop forever, so it is spent when used,
    and the second time round says what actually happened."""
    ui = Prefilled(
        {"branch-name-typed": "not a branch"},
        FakeUi(),
        interactive=False,
        flags={"branch-name-typed": "--branch-name"},
    )

    assert ui.text("Branch name", key="branch-name-typed") == "not a branch"

    with pytest.raises(NeedsAnswer) as raised:
        ui.text("Branch name", key="branch-name-typed")

    assert raised.value.flag == "--branch-name"
    assert "not accepted" in str(raised.value)


def test_the_default_answer_is_whatever_the_prompt_itself_defaults_to() -> None:
    """`--mode` defaults to `branch` and an unnamed branch to the first prefix — but
    neither of those strings is written down here. `DEFAULT` means *what pressing
    Enter would have taken*: the first option of a picker, the offered value of a text
    prompt. So reordering the menu or configuring different prefixes moves the command
    line's default with it, instead of leaving a copy behind to go stale."""
    ui = Prefilled(
        {"mode": Prefilled.DEFAULT, "branch-name-typed": Prefilled.DEFAULT},
        FakeUi(),
        interactive=False,
    )

    mode = ui.choose(
        "How should this lane start?",
        [Choice("branch", "branch"), Choice("detached", "detached")],
        key="mode",
    )
    typed = ui.text("Branch name", default="feature/pager", key="branch-name-typed")

    assert mode == "branch"
    assert typed == "feature/pager"
