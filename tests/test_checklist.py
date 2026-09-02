"""The checklist, driven through prompt_toolkit's pipe input.

Sits **below** the `Ui` seam exactly as the picker and the table do, and gets the
same treatment: a component with its own tests and no terminal anywhere near them.
Session-level tests replace the whole seam and never reach here.

It is the table's layout with a tick in front of every row, and it is the one
widget in lane that binds `Space` — deliberately, because a multi-select list that
cannot be toggled in place is the screen this component exists to replace.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterator

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import DummyOutput

from lane.ui.checklist import (
    CROSS,
    MIXED,
    PARTLY,
    TICK,
    UNSET,
    Walk,
    bindings_for,
    check,
    mark_for,
    paint,
    tail_rows,
)
from lane.ui.seam import BACK_LABEL, Abandoned, Answers, Cell, Column, Finish, Node, Quit, Row

COLUMNS = (
    Column("path"),
    Column("size", drop=1),
)


class SizedOutput(DummyOutput):
    """A terminal of a stated size, so narrowness and shortness are testable."""

    def __init__(self, columns: int = 100, rows: int = 40) -> None:
        self._columns = columns
        self._rows = rows

    def get_size(self) -> Size:
        return Size(rows=self._rows, columns=self._columns)


@pytest.fixture
def keys() -> Iterator[PipeInput]:
    with create_pipe_input() as pipe:
        yield pipe


def _leaf(path: str, size: str = "1.2 GB") -> Node[str]:
    return Node(
        row=Row(
            value=path,
            cells=(Cell(path), Cell(size, tone="dim")),
            detail=(f"{path} — from the main clone",),
        )
    )


def _folder(label: str, size: str, children: list[Node[str]]) -> Node[str]:
    return Node(
        row=Row(value=label, cells=(Cell(label), Cell(size, tone="dim"))),
        children=tuple(children),
    )


def _rows() -> list[Node[str]]:
    return [
        _leaf(path, size)
        for path, size in (
            ("apps/web/node_modules", "1.2 GB"),
            ("apps/web/.env", "1.4 KB"),
            ("apps/console/dist", "340 MB"),
        )
    ]


def _tree() -> list[Node[str]]:
    """A leaf, a folder holding a leaf and another folder, and a leaf. Five leaves."""
    return [
        _leaf("node_modules", "1.2 GB"),
        _folder(
            "apps/ · 3 ignored paths",
            "1.5 GB",
            [
                _leaf("apps/api/.env", "1 KB"),
                _folder(
                    "apps/web/ · 2 ignored paths",
                    "1.4 GB",
                    [_leaf("apps/web/node_modules", "1.4 GB"), _leaf("apps/web/.env", "2 KB")],
                ),
            ],
        ),
        _leaf(".env", "1.4 KB"),
    ]


def _check(
    keys: PipeInput,
    sent: str,
    *,
    answers: dict[str, bool] | None = None,
    columns: int = 120,
    rows: int = 40,
    nodes: Callable[[], list[Node[str]]] = _rows,
) -> Answers[str]:
    keys.send_text(sent)
    return check(
        "3 paths lane has not been told about",
        COLUMNS,
        nodes,
        answers=answers,
        input=keys,
        output=SizedOutput(columns, rows),
    )


_APPS = ("apps/api/.env", "apps/web/node_modules", "apps/web/.env")
"""Every leaf under `apps/` in `_tree`, which is what one Space on that folder answers."""

SPACE = " "
ENTER = "\r"
DOWN = "\x1b[B"
UP = "\x1b[A"
END = "\x1b[F"

APPLY_ROW = END + UP + ENTER
"""Finish the screen, from whatever level and wherever the cursor is standing.

`End` is the last row of any level — `discard` — and one Up from it is `apply`, because
those two end every level in that order. Written once and used everywhere so a test's
keys say *finish* rather than counting rows to get there.
"""

DISCARD_ROW = END + ENTER
"""Throw the screen away, from any level. `discard` is the last row there is."""


# -- ticking ---------------------------------------------------------------------


def test_space_answers_the_row_under_the_cursor_and_apply_returns_it(keys: PipeInput) -> None:
    """The whole point: the answer changes under the cursor, in place, one keystroke."""
    assert _check(keys, SPACE + APPLY_ROW) == {"apps/web/node_modules": True}


def test_a_dozen_answers_cost_a_dozen_keystrokes_and_a_walk_to_apply(keys: PipeInput) -> None:
    """Three rows, three spaces, then down to `apply` — no screen is entered and none is
    left. Walking to the last row is what the accept costs now that it is a row you can
    see rather than a meaning `Enter` carried on some rows and not others."""
    sent = SPACE + DOWN + SPACE + DOWN + SPACE + APPLY_ROW
    assert _check(keys, sent) == {
        "apps/web/node_modules": True,
        "apps/web/.env": True,
        "apps/console/dist": True,
    }


def test_space_twice_puts_the_row_explicitly_out(keys: PipeInput) -> None:
    """And *out* is now a recorded answer rather than the absence of one, which is what
    the third state bought: the row was decided, and it was decided against."""
    assert _check(keys, SPACE + SPACE + APPLY_ROW) == {"apps/web/node_modules": False}


def test_the_cursor_does_not_move_when_a_row_is_ticked(keys: PipeInput) -> None:
    """A list that advances on toggle makes correcting the row you just ticked a
    two-key job, and this screen's promise is one key."""
    assert _check(keys, SPACE * 3 + APPLY_ROW) == {"apps/web/node_modules": True}


def test_applying_an_untouched_screen_answers_nothing_at_all(keys: PipeInput) -> None:
    """Every row starts *unanswered*, so applying at once is always the safe answer — and
    it files no decision, rather than filing "out" for every row nobody looked at."""
    assert _check(keys, APPLY_ROW) == {}


def test_rows_already_answered_arrive_as_they_stand(keys: PipeInput) -> None:
    """Settings opens the same screen over answers given months ago, and it has to
    show them as they stand rather than as though nothing had been decided — including
    the ones answered *out*, which a set could not carry."""
    stored = {"apps/web/.env": True, "apps/console/dist": False}
    assert _check(keys, APPLY_ROW, answers=stored) == stored


def test_an_answered_row_can_be_taken_back_out(keys: PipeInput) -> None:
    sent = DOWN + SPACE + APPLY_ROW
    assert _check(keys, sent, answers={"apps/web/.env": True}) == {"apps/web/.env": False}


def test_ctrl_c_quits_lane_rather_than_backing_out(keys: PipeInput) -> None:
    """Ctrl-C is not this screen's way back — `discard` is, and `← Back` is the way up a
    level. What is left for Ctrl-C is the thing every terminal user already assumes it
    does, so it raises `Quit` rather than the `Abandoned` a visible row raises."""
    with pytest.raises(Quit):
        _check(keys, SPACE + "\x03")


def test_the_arrows_wrap(keys: PipeInput) -> None:
    """The picker wraps and so does the table — over every row of the level, the
    trailing ones included. So one Up from the top is the last of those."""
    up_from_the_top = _lines(cursor=len(_rows()))

    assert up_from_the_top[-1].strip().startswith("↑↓ move")
    assert any(line.startswith("❯") and line.strip().endswith("apply") for line in up_from_the_top)


def test_end_reaches_the_last_row_and_home_comes_back(keys: PipeInput) -> None:
    """`End` is the last row of the level — `discard`, with `apply` above it and the last
    path above that; `Home` is the first row, which is always a path."""
    sent = END + UP + UP + SPACE + "\x1b[H" + SPACE + APPLY_ROW
    assert _check(keys, sent) == {"apps/console/dist": True, "apps/web/node_modules": True}


# -- the tree: one level per screen ----------------------------------------------


def test_a_folder_is_opened_with_enter_and_shows_what_is_under_it(keys: PipeInput) -> None:
    """One level of the tree per screen. `Enter` on a folder is `Enter` doing what it
    does in the lanes table — acting on the row under the cursor.

    Driven by what the keys *did*: inside `apps/` a Space answers one path rather than
    the folder's three, which no cursor position on the level above could produce.
    """
    sent = DOWN + ENTER + SPACE + APPLY_ROW
    assert _check(keys, sent, nodes=_tree) == {"apps/api/.env": True}


def test_the_level_below_a_folder_holds_its_children_and_is_titled_by_it() -> None:
    """§1: a screen's title answers "what am I looking at". The folder row already
    said it, so opening one carries its own words down with it."""
    walk: Walk[str] = Walk(_tree)
    walk.index = 1

    assert walk.enter()
    nodes, title = walk.level()

    assert [node.row.value for node in nodes] == [
        "apps/api/.env",
        "apps/web/ · 2 ignored paths",
    ]
    assert title == "apps/ · 3 ignored paths"


def test_the_root_has_no_way_back_row_and_a_level_inside_one_does() -> None:
    """The root screen is the one with nothing above it, so its only exit is the footer's
    `ctrl-c`, exactly as before. Every level inside a folder is somewhere you can leave —
    visibly, with a row (docs/CONVENTIONS.md §2)."""
    root: Walk[str] = Walk(_tree)
    opened: Walk[str] = Walk(_tree)
    opened.index = 1
    opened.enter()

    assert not root.nested, "the root draws no way back"
    assert opened.nested

    assert not any("←" in line for line in _painted())
    inside = _painted(nested=True)
    assert any(line.strip() == BACK_LABEL for line in inside)


def test_the_way_back_row_goes_up_a_level_rather_than_out_of_the_screen(
    keys: PipeInput,
) -> None:
    """`←` means backwards, and inside a folder backwards is the level above — not the
    way out, which is `ctrl-c` and says so in the footer."""
    # Into `apps/`, down onto the `← Back` row (past both of its rows), Enter, then
    # answer the root's first leaf and accept.
    sent = DOWN + ENTER + DOWN + DOWN + ENTER + UP + SPACE + APPLY_ROW
    assert _check(keys, sent, nodes=_tree) == {"node_modules": True}


def test_going_up_returns_to_the_parent_with_its_rows_exactly_as_left(
    keys: PipeInput,
) -> None:
    """Leaving a folder puts you back where you were standing, with what you answered
    still answered — the cursor included, as `browse` already does for the lanes table."""
    # Down to `apps/`, open it, tick its first child, back out with the `← Back` row
    # (down twice from the first child), then Space — which must land on `apps/` again.
    sent = DOWN + ENTER + SPACE + DOWN + DOWN + ENTER + SPACE + APPLY_ROW
    assert _check(keys, sent, nodes=_tree) == {
        "apps/api/.env": True,
        "apps/web/node_modules": True,
        "apps/web/.env": True,
    }, (
        "the cursor came back onto `apps/`, whose one path answered inside it was still "
        "answered — so Space there found a mix and brought the whole folder in"
    )


def test_enter_on_a_leaf_does_nothing_at_all(keys: PipeInput) -> None:
    """A leaf is the one row `Enter` has nothing to do to: its answer is `Space`'s job
    and there is nothing to open.

    What it did instead was decided by how deep the screen happened to be — accept at the
    root, go up anywhere else — which is how a press on a **file** ended up leaving the
    level it was pressed in. Both are gone: the keys after it are simply still read.
    """
    assert _check(keys, ENTER + SPACE + APPLY_ROW) == {"apps/web/node_modules": True}

    with create_pipe_input() as deeper:
        two_deep = DOWN + ENTER + DOWN + ENTER
        assert _check(deeper, two_deep + ENTER + SPACE + APPLY_ROW, nodes=_tree) == {
            "apps/web/node_modules": True
        }, "the cursor never left `apps/web/`, so the Space answered the leaf standing there"


def test_space_on_a_folder_answers_every_path_beneath_it(keys: PipeInput) -> None:
    """The point of a folder row: nobody wants to descend into fourteen packages one at
    a time. One keystroke, every leaf under it, however deep."""
    sent = DOWN + SPACE + APPLY_ROW
    assert _check(keys, sent, nodes=_tree) == {
        "apps/api/.env": True,
        "apps/web/node_modules": True,
        "apps/web/.env": True,
    }


def test_space_on_a_folder_that_is_all_in_takes_all_of_it_out(keys: PipeInput) -> None:
    sent = DOWN + SPACE + APPLY_ROW
    everything = dict.fromkeys(_APPS, True)
    assert _check(keys, sent, answers=everything, nodes=_tree) == dict.fromkeys(_APPS, False)


def test_space_on_a_mixed_folder_brings_the_whole_subtree_in(keys: PipeInput) -> None:
    """Three states, one key: the answer someone reaching for a directory row wants is
    *in*, so a mix goes in first and only then out. The mix it replaced is gone — which
    is why the panel says how many it is about to move."""
    sent = DOWN + SPACE + APPLY_ROW
    mixed = {"apps/web/.env": True}
    assert _check(keys, sent, answers=mixed, nodes=_tree) == dict.fromkeys(_APPS, True)

    with create_pipe_input() as second:
        again = _check(second, DOWN + SPACE + SPACE + APPLY_ROW, answers=mixed, nodes=_tree)
    assert again == dict.fromkeys(_APPS, False), (
        "and the press after that takes the whole subtree out"
    )


def test_a_leaf_is_never_mixed_or_partly_answered() -> None:
    """A leaf stands for one value, so only the first three of the five can apply to it:
    `◐` and `?` are folder marks and cannot appear on a path."""
    lines = _painted(answers={"node_modules": True})
    leaf = next(
        line for line in lines if line.strip().endswith("1.2 GB") and "node_modules" in line
    )

    assert "✓" in leaf
    marks = [line[:4] for line in lines if line.strip().endswith("GB") or line.endswith("KB")]
    assert not any("◐" in mark or "?" in mark for mark in marks if "apps/ ·" not in mark)


def test_the_count_is_over_every_leaf_rather_than_the_rows_on_screen() -> None:
    """A folder row is one row standing for five paths; a count of rows would mean
    something different on every screen of the same tree."""
    lines = _painted(answers={"apps/web/.env": True}, total=5)

    assert any("1 of 5 in" in line for line in lines)


def test_the_footer_says_what_enter_will_do_to_the_row_under_the_cursor() -> None:
    """`Enter` does a different thing to each kind of row and nothing at all to a leaf,
    so the footer names whichever applies — a screen says what its keys do (§3)."""
    on_a_leaf = _painted(cursor=0)[-1]
    on_a_folder = _painted(cursor=1)[-1]

    assert "enter" not in on_a_leaf, "a footer that names a key doing nothing teaches a lie"
    assert "space" in on_a_leaf, "and the key that *does* answer a leaf is still named"
    assert "enter open" in on_a_folder


# -- what the screen says about itself -------------------------------------------


def _lines(
    *,
    answers: dict[str, bool] | None = None,
    cursor: int = 0,
    width: int = 120,
    height: int = 40,
    summary: str = "",
    text: str = "",
) -> list[str]:
    return paint(
        "3 paths lane has not been told about",
        COLUMNS,
        _rows(),
        answers=answers or {},
        cursor=cursor,
        top=0,
        width=width,
        height=height,
        summary=summary,
        text=text,
    ).lines


def _painted(
    *,
    answers: dict[str, bool] | None = None,
    cursor: int = 0,
    total: int | None = None,
    nested: bool = False,
) -> list[str]:
    return paint(
        "5 paths lane has not been told about",
        COLUMNS,
        _tree(),
        answers=answers or {},
        cursor=cursor,
        top=0,
        width=120,
        height=40,
        total=total,
        nested=nested,
    ).lines


def test_a_row_that_is_in_ticks_one_that_is_out_crosses_and_an_untouched_one_rings() -> None:
    """Three marks for three answers. `✓` and `✗` are already in the symbol set and gain
    a meaning rather than a glyph; `○` is the one *unanswered* needed, because the state
    it replaced was the absence of a mark and so could not be told from either."""
    lines = _lines(answers={"apps/web/.env": True, "apps/console/dist": False})
    inside = next(line for line in lines if "apps/web/.env" in line)
    outside = next(line for line in lines if "apps/console/dist" in line)
    untouched = next(line for line in lines if "apps/web/node_modules" in line)

    assert "✓" in inside
    assert "✗" in outside and "✓" not in outside
    assert "○" in untouched and "✓" not in untouched and "✗" not in untouched


def test_the_screen_keeps_a_running_count_of_what_is_in() -> None:
    """Forty rows do not fit on a screen, so the one number that says what you have
    decided has to be somewhere you are already looking."""
    assert any("1 of 3 in" in line for line in _lines(answers={"apps/web/.env": True}))


def test_the_count_says_nothing_is_in_rather_than_zero() -> None:
    assert any("nothing in yet" in line for line in _lines())


def test_the_caller_can_add_what_the_widget_cannot_know() -> None:
    """How many is the widget's; how much is the action's — it owns the sizes."""
    lines = _lines(answers={"apps/web/.env": True}, summary="1.4 KB coming in")
    line = next(line for line in lines if "of 3 in" in line)

    assert line.strip() == "1 of 3 in · 1.4 KB coming in"


def test_the_footer_names_space_because_space_is_the_key_this_screen_adds() -> None:
    """One hint string per widget (docs/CONVENTIONS.md §2), and the way out is in it
    rather than in a row — a checklist has nothing to choose between."""
    footer = _lines()[-1]

    assert "space" in footer
    assert "ctrl-c" not in "\n".join(_lines()), (
        "the way out is the `discard` row now, and Ctrl-C is the one thing about a "
        "terminal program nobody has to be taught"
    )
    assert "←" not in "\n".join(_lines()), "the root has nowhere to go back to"


# -- layout under pressure -------------------------------------------------------


def test_more_rows_than_room_scroll_and_the_footer_says_where_you_are() -> None:
    """Forty loose files in one folder is a real screen, and the widget it replaced
    could not scroll — which is why this is not `CheckboxList`."""
    rows = [_leaf(f"logs/app{n}.log", "2 KB") for n in range(40)]
    painted = paint("40 paths", COLUMNS, rows, answers={}, cursor=0, top=0, width=120, height=20)
    shown = len(rows) + len(tail_rows(nested=False))

    assert painted.room < shown
    assert f"1–{painted.room} of {shown}" in painted.lines[-1]


def test_the_cursor_stays_on_screen_when_it_walks_past_the_window() -> None:
    rows = [_leaf(f"path-{n}", "2 KB") for n in range(40)]
    painted = paint("40 paths", COLUMNS, rows, answers={}, cursor=39, top=0, width=120, height=20)

    assert any("path-39" in line for line in painted.lines)
    assert painted.top > 0


def test_the_tick_survives_a_forty_column_terminal() -> None:
    """§13: the column answering the screen's own question is never dropped and never
    truncated. Here that is the tick — everything else gives way first."""
    path = "apps/web/frontend/node_modules/.pnpm/store"
    rows = [_leaf(path, "1.2 GB")]
    lines = paint(
        "1 path",
        COLUMNS,
        rows,
        answers={path: True},
        cursor=0,
        top=0,
        width=40,
        height=40,
    ).lines
    row = next(line for line in lines if "node_modules" in line)

    assert "✓" in row
    assert "1.2 GB" not in row, "size is the droppable column"
    assert "…" in row, "and the path is what gives way"
    assert len(row) <= 40


def _ignore(result: object) -> None:
    """Stand in for `Application.exit`: nothing here runs a handler."""
    del result


def test_the_widget_binds_the_pickers_keys_plus_space_and_nothing_else() -> None:
    """Asserted on the binding table rather than by driving keys, because a bound
    handler that happens to do nothing still swallows the keystroke."""
    bindings = bindings_for(Walk(_rows), {}, _ignore)
    bound = {key for binding in bindings.bindings for key in binding.keys}

    assert bound == {
        Keys.Up,
        Keys.Down,
        Keys.Home,
        Keys.End,
        Keys.ControlM,
        Keys.ControlC,
        " ",
        # Typing filters and Backspace takes a character back, from the one
        # `filtering.bind` the picker and the table also call. `Space` is still bound
        # here and nowhere else, which is what this test is for: an exact binding
        # outranks the `Any` catch-all, so it answers a row rather than typing one.
        Keys.Any,
        Keys.ControlH,
    }


def test_a_slow_column_lands_behind_the_screen_you_are_already_reading(keys: PipeInput) -> None:
    """`du` on a large tree is slow and the sizes are what stop someone bringing in a
    database by accident, so they have to arrive without holding up the first paint."""
    sizes = {"apps/web/node_modules": "measuring…"}
    painted: list[str] = []
    drawn = threading.Event()
    landed = threading.Event()

    def rows() -> list[Node[str]]:
        return [_leaf("apps/web/node_modules", sizes["apps/web/node_modules"])]

    def watch(line: str) -> None:
        painted.append(line)
        if "measuring…" in line:
            drawn.set()
        if "1.2 GB" in line:
            landed.set()

    def measure(notify: object) -> None:
        assert callable(notify)
        # Wait for the first paint rather than racing it: the claim is that the rows
        # were already on screen, and a fill that finished first would not test it.
        drawn.wait(30)
        sizes["apps/web/node_modules"] = "1.2 GB"
        notify()
        landed.wait(30)
        keys.send_text(APPLY_ROW)

    check(
        "1 path",
        COLUMNS,
        rows,
        fill=measure,
        on_render=watch,
        input=keys,
        output=SizedOutput(120, 40),
    )

    assert any("measuring…" in line for line in painted), "the rows were on screen first"
    assert any("1.2 GB" in line for line in painted), "and the size arrived behind them"


def test_ctrl_c_quits_from_any_depth_rather_than_going_up_one_level(keys: PipeInput) -> None:
    """The report said Ctrl-C went up a folder. It never did in this code — it abandoned
    the whole screen from any depth — but it is worth a test at depth either way, because
    "up one level" is a plausible thing for a nested screen to have grown."""
    with pytest.raises(Quit):
        _check(keys, DOWN + ENTER + DOWN + ENTER + SPACE + "\x03", nodes=_tree)


def test_the_prefix_a_level_shares_gives_way_before_the_path_does() -> None:
    """Inside a folder every row starts with the same directory, so it identifies
    nothing — which is what `Cell.lead` is for, and why it goes first (§13)."""
    shared = "packages/web/frontend/"
    rows = [
        Node(row=Row(value=name, cells=(Cell(name, lead=shared), Cell("1.2 GB", tone="dim"))))
        for name in ("node_modules", "dist")
    ]
    lines = paint(
        f"{shared} · 2 ignored paths",
        COLUMNS,
        rows,
        answers={"node_modules": True},
        cursor=0,
        top=0,
        width=30,
        height=20,
        nested=True,
    ).lines
    row = next(line for line in lines if "node_modules" in line and "·" not in line)

    assert shared not in row, "the shared prefix is what gives way"
    assert "node_modules" in row and "…" not in row
    assert "✓" in row


def test_the_footer_gives_up_the_arrows_before_the_keys_on_a_narrow_terminal() -> None:
    """It sheds what can be spared, in order: the arrows first, because nobody needs
    telling that arrows move; then what each key does. The keys themselves survive."""
    narrow = _lines(width=20)[-1]

    assert "space" in narrow
    assert "↑↓" not in narrow
    assert len(narrow) <= 20


def test_the_footer_keeps_the_arrows_when_there_is_room() -> None:
    assert "↑↓ move" in _lines(width=120)[-1]


def _two_folders() -> list[Node[str]]:
    """Two sibling folders at the root, so leaving one and going into the other is a walk
    a test can actually take."""
    return [
        _folder("apps/ · 2 ignored paths", "1 GB", [_leaf("apps/one"), _leaf("apps/two")]),
        _folder("libs/ · 2 ignored paths", "2 GB", [_leaf("libs/one"), _leaf("libs/two")]),
    ]


def test_enter_opens_a_folder_at_the_root_and_inside_another_open_one(keys: PipeInput) -> None:
    """The one thing `Enter` on a row has always meant in lane — act on the row under the
    cursor — and depth changes nothing about it."""
    walk: Walk[str] = Walk(_tree)
    walk.index = 1

    assert walk.enter(), "at the root"
    walk.index = 1
    assert walk.enter(), "and inside the folder that opened"
    nodes, title = walk.level()

    assert [node.row.value for node in nodes] == ["apps/web/node_modules", "apps/web/.env"]
    assert title == "apps/web/ · 2 ignored paths"

    # And through the keys, at the deeper of the two: a Space there answers one leaf,
    # which no cursor position on either level above could produce.
    assert _check(keys, DOWN + ENTER + DOWN + ENTER + SPACE + APPLY_ROW, nodes=_tree) == {
        "apps/web/node_modules": True
    }


def test_the_way_back_row_keeps_every_answer_made_inside_the_level_it_leaves(
    keys: PipeInput,
) -> None:
    """`← Back` moves the cursor. It is not a second `discard`, and nothing about a row
    labelled *back* should have to be read as *and throw away what you just decided*."""
    # Into `apps/`, answer its first leaf, down onto `← Back`, up and out — then apply
    # from the root without touching anything else.
    sent = DOWN + ENTER + SPACE + DOWN + DOWN + ENTER + APPLY_ROW

    assert _check(keys, sent, nodes=_tree) == {"apps/api/.env": True}


def test_an_answer_two_levels_down_survives_walking_back_out_and_into_another_folder(
    keys: PipeInput,
) -> None:
    """The answers are one set for the whole visit, and the walk does not touch it. Held
    down by a test rather than by the shape of the code, because it is the sort of
    guarantee a later refactor of the descent could quietly drop."""
    into, back_out = ENTER, DOWN + DOWN + ENTER

    # Into `apps/`, answer its first leaf, back out; into `libs/`, answer its first, back
    # out; then apply from the root.
    sent = into + SPACE + back_out + DOWN + into + SPACE + back_out + APPLY_ROW

    assert _check(keys, sent, nodes=_two_folders) == {"apps/one": True, "libs/one": True}


def test_apply_from_a_nested_level_commits_every_answer_made_at_any_depth(
    keys: PipeInput,
) -> None:
    """`apply` ends the **screen**, not the level it was pressed on — the one place the
    old accept genuinely was per-level, and the source of the "a stray Enter cannot end
    preparation from three levels down" reasoning that no longer has anything to guard."""
    # Answer a root leaf, then walk two levels down, answer one there, and apply without
    # ever coming back up.
    sent = SPACE + DOWN + ENTER + DOWN + ENTER + SPACE + APPLY_ROW

    assert _check(keys, sent, nodes=_tree) == {
        "node_modules": True,
        "apps/web/node_modules": True,
    }


# -- apply and discard, on every level -------------------------------------------


def test_apply_is_a_row_at_the_root_and_enter_on_it_accepts(keys: PipeInput) -> None:
    """A screen with no reachable "I am done" is a screen you cannot leave forwards, and
    that is what the root had: `Enter` accepted only from a **root-level leaf**, and a
    repository whose ignored paths are all grouped under folders has none of those.

    So accepting is a row, like `← Back` is — reachable by moving the cursor onto it,
    which needs no knowledge of what `Enter` happens to mean where you are standing.
    """
    assert any(line.strip() == "apply" for line in _lines())

    # Three leaves, so three presses of Down land on `apply` — which answers nothing,
    # so the Space is a no-op and applying returns what was decided before it: nothing.
    assert _check(keys, DOWN * 3 + SPACE + ENTER) == {}


def test_discard_is_a_row_at_the_root_and_enter_on_it_abandons(keys: PipeInput) -> None:
    """The way out is a row too, for the same reason the way back always has been: a
    screen whose only exit is a keystroke is one you have to be taught to leave.

    It abandons, exactly as it always did — the widget answers `None`, which `check`
    turns into `Abandoned`, so nothing an action was going to write gets written.
    """
    assert any(line.strip() == "discard" for line in _lines())

    with pytest.raises(Abandoned):
        _check(keys, SPACE + DISCARD_ROW)


def test_the_two_rows_say_what_they_will_do_while_the_cursor_is_on_them() -> None:
    """`apply` and `discard` are one verb each, and a verb does not say how much it
    covers. The panel the tree's rows already use is where that goes — and `discard` is
    the row that has to have it, being the only one on screen that throws work away."""
    on_apply = "\n".join(_lines(cursor=len(_rows())))
    on_discard = "\n".join(_lines(cursor=len(_rows()) + 1))

    assert "asked again" in on_apply
    assert "thrown away" in on_discard


def test_apply_and_discard_are_on_every_level_and_come_after_the_way_back(
    keys: PipeInput,
) -> None:
    """ "Always", not "after you have walked back up to the top".

    Reachable only from the root is what the accept used to be, and it made a nested
    level a place you could get into and not finish from — you had to remember the way
    out was `← Back`, repeatedly, before the screen would let you say you were done.
    """
    inside = _painted(nested=True)
    trailing = [line.strip() for line in inside if line.strip() in {BACK_LABEL, "apply", "discard"}]

    assert trailing == [BACK_LABEL, "apply", "discard"], "the way back belongs with the tree"

    # Two levels down — root, into `apps/`, into `apps/web/` — and finish from there.
    two_deep = DOWN + ENTER + DOWN + ENTER
    assert _check(keys, two_deep + SPACE + APPLY_ROW, nodes=_tree) == {
        "apps/web/node_modules": True
    }


def test_discard_two_levels_down_abandons_the_whole_screen(keys: PipeInput) -> None:
    with pytest.raises(Abandoned):
        _check(keys, DOWN + ENTER + DOWN + ENTER + SPACE + DISCARD_ROW, nodes=_tree)


# -- five states per folder ------------------------------------------------------


def _pkg(*names: str) -> Node[str]:
    """A folder of loose leaves — the shape every state below is measured on."""
    return _folder(f"pkg/ · {len(names)} ignored paths", "1 GB", [_leaf(name) for name in names])


ALL, SOME = ("a", "b", "c"), ("a", "b")


@pytest.mark.parametrize(
    ("answers", "mark", "state"),
    [
        ({}, UNSET, "nothing beneath it answered"),
        (dict.fromkeys(ALL, True), TICK, "every leaf in"),
        (dict.fromkeys(ALL, False), CROSS, "every leaf explicitly out"),
        ({"a": True, "b": False, "c": True}, MIXED, "all decided, and they disagree"),
        ({"a": True, "b": False}, PARTLY, "a mix, and one leaf still unanswered"),
        (dict.fromkeys(SOME, True), PARTLY, "all in but one, which is unanswered"),
        (dict.fromkeys(SOME, False), PARTLY, "all out but one, which is unanswered"),
        ({"a": True}, PARTLY, "one answered, two still unanswered"),
    ],
)
def test_a_folder_draws_which_of_the_five_states_it_is_in(
    answers: dict[str, bool], mark: str, state: str
) -> None:
    """Five, not two: a folder stands for paths that are not on screen, so every state
    those paths can be collectively in needs a mark that does not lie about them.

    `?` and `◐` are the pair worth being careful about — *there is still a question under
    here* and *this is decided, and mixed* are different facts, and only one of them is
    something the user still has to come back to.
    """
    assert mark_for(_pkg(*ALL), answers) == mark, state


def test_the_five_states_are_exhaustive_and_mutually_exclusive() -> None:
    """Every way three leaves can be answered lands in exactly one of the five, and in
    the one the partition names. Asserted over the whole space rather than over the two
    cases that used to exist, because "exhaustive" is not a claim a sample can make."""
    folder = _pkg(*ALL)

    for combination in itertools.product((True, False, None), repeat=len(ALL)):
        answers = {
            name: value for name, value in zip(ALL, combination, strict=True) if value is not None
        }
        inside, outside, unset = (combination.count(one) for one in (True, False, None))
        mark = mark_for(folder, answers)
        held = {
            UNSET: unset == len(ALL),
            PARTLY: 0 < unset < len(ALL),
            TICK: unset == 0 and inside == len(ALL),
            CROSS: unset == 0 and outside == len(ALL),
            MIXED: unset == 0 and 0 < inside < len(ALL),
        }

        assert sum(held.values()) == 1, f"{combination} is in more than one state at once"
        assert held[mark], f"{combination} drew {mark!r}, which its counts do not describe"


def test_no_two_of_the_five_marks_are_told_apart_by_colour_alone() -> None:
    """§6: colour never carries meaning alone — and three of the five are drawn `warn`,
    so the glyphs are the whole of what distinguishes them."""
    marks = [TICK, CROSS, UNSET, PARTLY, MIXED]

    assert len(set(marks)) == len(marks)
    assert len({mark.strip() for mark in marks}) == len(marks)


def test_a_folders_state_is_drawn_on_its_row() -> None:
    """The partition is only worth having if it reaches the screen: `apps/` holds three
    leaves, one of them answered, so it is the folder with a question still in it."""
    partly = next(line for line in _painted(answers={"apps/web/.env": True}) if "apps/ · 3" in line)
    decided = next(
        line
        for line in _painted(answers=dict.fromkeys(_APPS, True) | {"apps/web/.env": False})
        if "apps/ · 3" in line
    )
    untouched = next(line for line in _painted() if "apps/ · 3" in line)

    assert "?" in partly and "◐" not in partly
    assert "◐" in decided and "?" not in decided
    assert "○" in untouched


# -- three answers per leaf ------------------------------------------------------


def test_a_leaf_starts_unset_and_an_untouched_screen_answers_nothing(keys: PipeInput) -> None:
    """*Never touched this visit* is an answer the old two-state set could not hold: it
    collapsed into *out*, so accepting a screen wrote a `skip` for every row nobody had
    looked at. An untouched screen now answers nothing at all."""
    assert _check(keys, APPLY_ROW) == {}


def test_space_takes_a_leaf_in_then_out_and_never_back_to_unset(keys: PipeInput) -> None:
    """Unset is where a row *starts*, not somewhere `Space` can put it back: the first
    press answers the question, and every press after it changes the answer."""
    path = "apps/web/node_modules"

    assert _check(keys, SPACE + APPLY_ROW) == {path: True}
    with create_pipe_input() as second:
        assert _check(second, SPACE * 2 + APPLY_ROW) == {path: False}
    with create_pipe_input() as third:
        assert _check(third, SPACE * 3 + APPLY_ROW) == {path: True}
    with create_pipe_input() as fourth:
        assert _check(fourth, SPACE * 4 + APPLY_ROW) == {path: False}


# -- the caller's own words for the two rows that end a level --------------------


CLOSING = Finish(
    accept="close",
    reject="leave open",
    accept_detail="Closes the lane, doing exactly what is ticked above.",
    reject_detail="Leaves the lane exactly as it is. Nothing is touched.",
)
"""What the close screen ends with — `apply`/`discard` in a different vocabulary."""


def test_the_caller_names_the_two_rows_that_end_a_level() -> None:
    """`apply` and `discard` are the checklist's words for *what a screen of ignored
    paths does*, and a screen of decisions about closing a lane does something else.

    The rows are still the same two — the way on and the way out — so they stay rows
    rather than becoming keys; only the words are the caller's, exactly as `← Back`'s
    label already is a constant the seam owns rather than one the widget invents.
    """

    def drawn(cursor: int) -> list[str]:
        return paint(
            "Closing thing/mylane",
            COLUMNS,
            _rows(),
            answers={},
            cursor=cursor,
            top=0,
            width=120,
            height=40,
            finish=CLOSING,
        ).lines

    lines = drawn(0)
    assert any(line.strip() == "close" for line in lines)
    assert any(line.strip() == "leave open" for line in lines)
    assert not any(line.strip() in {"apply", "discard"} for line in lines)

    # The panel is the caller's too: one verb cannot say how much it covers.
    assert "doing exactly what is ticked" in "\n".join(drawn(len(_rows())))
    assert "Nothing is touched" in "\n".join(drawn(len(_rows()) + 1))


def test_enter_on_the_callers_accept_row_returns_the_answers(keys: PipeInput) -> None:
    keys.send_text(SPACE + APPLY_ROW)
    assert check(
        "Closing thing/mylane",
        COLUMNS,
        _rows,
        input=keys,
        output=SizedOutput(120, 40),
        finish=CLOSING,
    ) == {"apps/web/node_modules": True}


def test_enter_on_the_callers_reject_row_abandons(keys: PipeInput) -> None:
    keys.send_text(DISCARD_ROW)
    with pytest.raises(Abandoned):
        check(
            "Closing thing/mylane",
            COLUMNS,
            _rows,
            input=keys,
            output=SizedOutput(120, 40),
            finish=CLOSING,
        )


@pytest.mark.parametrize(
    ("accept", "reject"),
    [
        pytest.param("close", "close", id="the way on and the way out read alike"),
        pytest.param(BACK_LABEL, "leave open", id="the way on reads as the back row"),
        pytest.param("close", BACK_LABEL, id="the way out reads as the back row"),
    ],
)
def test_a_level_cannot_end_with_two_rows_that_read_alike(accept: str, reject: str) -> None:
    """Which trailing row `Enter` acted on was decided by comparing its label, so two
    that read alike left one of them unreachable — a screen with no way to accept it,
    or none to leave it. Refused where it is built, because a `Finish` is made once at
    import and a screen that cannot be finished is not a thing to find out at runtime.
    """
    with pytest.raises(ValueError):
        Finish(accept=accept, reject=reject)


@pytest.mark.parametrize(("accept", "reject"), [("", "leave open"), ("close", "")])
def test_a_row_that_ends_a_level_has_a_word_on_it(accept: str, reject: str) -> None:
    """A blank label is the same screen as a colliding one: a row nobody can read is a
    row nobody can choose, so it is refused in the same place and for the same reason.
    """
    with pytest.raises(ValueError):
        Finish(accept=accept, reject=reject)


def test_the_checklists_footer_is_the_shared_corner_hint() -> None:
    """One renderer for every screen's corner (`ui/footer.py`). This screen's key set
    is the only one that changes with the cursor, and it is still the same renderer
    that draws it. If the checklist went back to building its own string, this fails."""
    from lane.ui import footer
    from lane.ui.checklist import keys_for

    assert _painted(cursor=1)[-1] == footer.line(keys_for("open"), 120)
    assert _painted(cursor=0)[-1] == footer.line(keys_for(""), 120)


# -- type to filter ---------------------------------------------------------------


def test_typing_narrows_the_level_to_the_rows_that_match(keys: PipeInput) -> None:
    """One `Space` then `apply`, on a screen narrowed to the one row that matched —
    which is three keystrokes fewer than walking to it, and the same filter the picker
    and the table now have."""
    assert _check(keys, "console" + SPACE + APPLY_ROW) == {"apps/console/dist": True}


def test_the_filter_is_named_under_the_title_rather_than_being_a_mode() -> None:
    body = "\n".join(_lines(text="console"))

    assert "1 of 3 · filter: console" in body
    assert "apps/web/.env" not in body


def test_a_filter_matching_nothing_leaves_one_line_and_the_rows_that_end_the_screen() -> None:
    """docs/CONVENTIONS.md §12: one line, no table, no header — and `apply`/`discard`
    survive, because a screen you cannot finish or leave is not an empty state."""
    lines = _lines(text="zzz")
    body = "\n".join(lines)

    assert "No matches for 'zzz'." in body
    assert "node_modules" not in body, "no data rows"
    assert not any("path" in line and "size" in line for line in lines), "and no header"
    assert "apply" in body and "discard" in body


def test_a_filter_matching_nothing_can_still_be_discarded(keys: PipeInput) -> None:
    with pytest.raises(Abandoned):
        _check(keys, "zzz" + END + ENTER)


def test_the_filter_is_per_screen_so_a_level_starts_with_a_fresh_one() -> None:
    """One level is one screen, and the filter belongs to the screen: the word that
    found a folder does not go on hiding rows inside it, or back out of it."""
    walk: Walk[str] = Walk(_tree)
    walk.typed.text = "apps"

    assert walk.enter(), "the one row `apps` left is the folder"
    assert walk.typed.text == ""

    walk.typed.text = "env"
    assert walk.leave()
    assert walk.typed.text == ""


def test_the_descent_is_recorded_in_the_levels_own_rows_not_the_filtered_ones() -> None:
    """A folder is the folder you opened however you found it — otherwise a filter that
    put it second on screen would send the next paint into whatever is second in the
    unfiltered level."""
    walk: Walk[str] = Walk(_tree)
    walk.typed.text = "apps"
    walk.enter()

    nodes, title = walk.level()

    assert title == "apps/ · 3 ignored paths"
    assert [node.row.value for node in nodes] == ["apps/api/.env", "apps/web/ · 2 ignored paths"]


def test_the_second_caller_of_check_filters_and_says_so_in_the_same_corner() -> None:
    """The close screen is a checklist too, with its own words for the two rows that end
    it — so the filter and the corner have to be right there as well, and they are the
    same ones because they come from the same two functions rather than per screen."""
    lines = paint(
        "Closing thing/mylane",
        COLUMNS,
        _rows(),
        answers={},
        cursor=0,
        top=0,
        width=120,
        height=40,
        finish=CLOSING,
        text="zzz",
    ).lines
    body = "\n".join(lines)

    assert "No matches for 'zzz'." in body
    assert "close" in body and "leave open" in body, "the rows that end the screen survive"
    assert lines[-1].endswith("type to filter")
