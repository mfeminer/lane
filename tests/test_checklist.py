"""The checklist, driven through prompt_toolkit's pipe input.

Sits **below** the `Ui` seam exactly as the picker and the table do, and gets the
same treatment: a component with its own tests and no terminal anywhere near them.
Session-level tests replace the whole seam and never reach here.

It is the table's layout with a tick in front of every row, and it is the one
widget in lane that binds `Space` — deliberately, because a multi-select list that
cannot be toggled in place is the screen this component exists to replace.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import DummyOutput

from lane.ui.checklist import bindings_for, check, paint
from lane.ui.seam import Abandoned, Cell, Column, Row

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


def _rows() -> list[Row[str]]:
    return [
        Row(
            value=path,
            cells=(Cell(path), Cell(size, tone="dim")),
            detail=(f"{path} — from the main clone",),
        )
        for path, size in (
            ("apps/web/node_modules", "1.2 GB"),
            ("apps/web/.env", "1.4 KB"),
            ("apps/console/dist", "340 MB"),
        )
    ]


def _check(
    keys: PipeInput,
    sent: str,
    *,
    checked: tuple[str, ...] = (),
    columns: int = 120,
    rows: int = 40,
) -> frozenset[str]:
    keys.send_text(sent)
    return check(
        "3 paths lane has not been told about",
        COLUMNS,
        _rows,
        checked=checked,
        input=keys,
        output=SizedOutput(columns, rows),
    )


SPACE = " "
ENTER = "\r"
DOWN = "\x1b[B"


# -- ticking ---------------------------------------------------------------------


def test_space_ticks_the_row_under_the_cursor_and_enter_returns_it(keys: PipeInput) -> None:
    """The whole point: the answer changes under the cursor, in place, one keystroke."""
    assert _check(keys, SPACE + ENTER) == {"apps/web/node_modules"}


def test_a_dozen_answers_cost_a_dozen_keystrokes_plus_one(keys: PipeInput) -> None:
    """Three rows, three spaces, one Enter — no screen is entered and none is left."""
    sent = SPACE + DOWN + SPACE + DOWN + SPACE + ENTER
    assert _check(keys, sent) == {"apps/web/node_modules", "apps/web/.env", "apps/console/dist"}


def test_space_twice_puts_the_row_back_out(keys: PipeInput) -> None:
    """Two states and only two: there is no third press to get lost in."""
    assert _check(keys, SPACE + SPACE + ENTER) == frozenset()


def test_the_cursor_does_not_move_when_a_row_is_ticked(keys: PipeInput) -> None:
    """A list that advances on toggle makes correcting the row you just ticked a
    two-key job, and this screen's promise is one key."""
    assert _check(keys, SPACE + SPACE + SPACE + ENTER) == {"apps/web/node_modules"}


def test_enter_accepts_an_untouched_screen_as_nothing_in(keys: PipeInput) -> None:
    """Every row starts out, so one Enter is always the safe answer."""
    assert _check(keys, ENTER) == frozenset()


def test_rows_already_answered_arrive_ticked(keys: PipeInput) -> None:
    """Settings opens the same screen over answers given months ago, and it has to
    show them as they stand rather than as though nothing had been decided."""
    assert _check(keys, ENTER, checked=("apps/web/.env",)) == {"apps/web/.env"}


def test_an_answered_row_can_be_taken_back_out(keys: PipeInput) -> None:
    sent = DOWN + SPACE + ENTER
    assert _check(keys, sent, checked=("apps/web/.env",)) == frozenset()


def test_ctrl_c_backs_out_and_answers_nothing(keys: PipeInput) -> None:
    with pytest.raises(Abandoned):
        _check(keys, SPACE + "\x03")


def test_the_arrows_wrap(keys: PipeInput) -> None:
    """The picker wraps and so does the table; with no back row, this wraps over rows."""
    assert _check(keys, "\x1b[A" + SPACE + ENTER) == {"apps/console/dist"}


def test_end_reaches_the_last_row_and_home_comes_back(keys: PipeInput) -> None:
    sent = "\x1b[F" + SPACE + "\x1b[H" + SPACE + ENTER
    assert _check(keys, sent) == {"apps/console/dist", "apps/web/node_modules"}


# -- what the screen says about itself -------------------------------------------


def _lines(
    *,
    checked: frozenset[str] = frozenset(),
    cursor: int = 0,
    width: int = 120,
    height: int = 40,
    summary: str = "",
) -> list[str]:
    return paint(
        "3 paths lane has not been told about",
        COLUMNS,
        _rows(),
        checked=checked,
        cursor=cursor,
        top=0,
        width=width,
        height=height,
        summary=summary,
    ).lines


def test_a_ticked_row_draws_the_tick_and_an_unticked_one_draws_nothing() -> None:
    """`✓` is already in the symbol set; it gains a meaning rather than a glyph."""
    lines = _lines(checked=frozenset({"apps/web/.env"}))
    ticked = next(line for line in lines if "apps/web/.env" in line)
    untouched = next(line for line in lines if "apps/console/dist" in line)

    assert "✓" in ticked
    assert "✓" not in untouched


def test_the_screen_keeps_a_running_count_of_what_is_in() -> None:
    """Forty rows do not fit on a screen, so the one number that says what you have
    decided has to be somewhere you are already looking."""
    assert any("1 of 3 in" in line for line in _lines(checked=frozenset({"apps/web/.env"})))


def test_the_count_says_nothing_is_in_rather_than_zero() -> None:
    assert any("nothing in yet" in line for line in _lines())


def test_the_caller_can_add_what_the_widget_cannot_know() -> None:
    """How many is the widget's; how much is the action's — it owns the sizes."""
    lines = _lines(checked=frozenset({"apps/web/.env"}), summary="1.4 KB coming in")
    line = next(line for line in lines if "of 3 in" in line)

    assert line.strip() == "1 of 3 in · 1.4 KB coming in"


def test_the_footer_names_space_because_space_is_the_key_this_screen_adds() -> None:
    """One hint string per widget (docs/CONVENTIONS.md §2), and the way out is in it
    rather than in a row — a checklist has nothing to choose between."""
    footer = _lines()[-1]

    assert "space toggle" in footer
    assert "enter accept" in footer
    assert "ctrl-c back out" in footer
    assert "←" not in "\n".join(_lines()), "no Back row: the footer is the visible exit"


# -- layout under pressure -------------------------------------------------------


def test_more_rows_than_room_scroll_and_the_footer_says_where_you_are() -> None:
    """Forty loose files in one folder is a real screen, and the widget it replaced
    could not scroll — which is why this is not `CheckboxList`."""
    rows = [
        Row(value=f"logs/app{n}.log", cells=(Cell(f"logs/app{n}.log"), Cell("2 KB")))
        for n in range(40)
    ]
    painted = paint(
        "40 paths", COLUMNS, rows, checked=frozenset(), cursor=0, top=0, width=120, height=20
    )

    assert painted.room < 40
    assert f"1–{painted.room} of 40" in painted.lines[-1]


def test_the_cursor_stays_on_screen_when_it_walks_past_the_window() -> None:
    rows = [Row(value=str(n), cells=(Cell(f"path-{n}"), Cell("2 KB"))) for n in range(40)]
    painted = paint(
        "40 paths", COLUMNS, rows, checked=frozenset(), cursor=39, top=0, width=120, height=20
    )

    assert any("path-39" in line for line in painted.lines)
    assert painted.top > 0


def test_the_tick_survives_a_forty_column_terminal() -> None:
    """§13: the column answering the screen's own question is never dropped and never
    truncated. Here that is the tick — everything else gives way first."""
    path = "apps/web/frontend/node_modules/.pnpm/store"
    rows = [Row(value=path, cells=(Cell(path), Cell("1.2 GB", tone="dim")))]
    lines = paint(
        "1 path",
        COLUMNS,
        rows,
        checked=frozenset({path}),
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
    state = {"index": 0, "top": 0, "rows": 3}
    bindings = bindings_for(state, _rows, set(), _ignore)
    bound = {key for binding in bindings.bindings for key in binding.keys}

    assert bound == {
        Keys.Up,
        Keys.Down,
        Keys.Home,
        Keys.End,
        Keys.ControlM,
        Keys.ControlC,
        " ",
    }


def test_a_slow_column_lands_behind_the_screen_you_are_already_reading(keys: PipeInput) -> None:
    """`du` on a large tree is slow and the sizes are what stop someone bringing in a
    database by accident, so they have to arrive without holding up the first paint."""
    sizes = {"apps/web/node_modules": "measuring…"}
    painted: list[str] = []
    drawn = threading.Event()
    landed = threading.Event()

    def rows() -> list[Row[str]]:
        return [
            Row(
                value="apps/web/node_modules",
                cells=(Cell("apps/web/node_modules"), Cell(sizes["apps/web/node_modules"])),
            )
        ]

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
        keys.send_text(ENTER)

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


def test_the_way_out_stays_readable_on_a_narrow_terminal() -> None:
    """§2's rule is that the one way out is *visible*. A hint clipped to `ctr…` is not,
    so the footer gives up its least surprising part — the arrows — before it gives up
    naming Ctrl-C."""
    footer = _lines(width=46)[-1]

    assert "ctrl-c back out" in footer
    assert "space" in footer
    assert len(footer) <= 46


def test_the_footer_keeps_the_arrows_when_there_is_room() -> None:
    assert "↑↓ move" in _lines(width=120)[-1]
