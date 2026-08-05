"""The interactive table, driven through prompt_toolkit's pipe input.

Sits **below** the `Ui` seam exactly as the picker does, and gets the same
treatment: a component with its own tests and no terminal anywhere near them.
Session-level tests replace the whole seam and never reach here.

Layout is asserted through `paint`, which is pure: it takes a width and a height
and returns the lines it would draw. Key handling is asserted through `browse`,
which is the picker's binding set and nothing more.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.output import DummyOutput

from lane.ui.seam import Abandoned, Cell, Column, Row
from lane.ui.table import browse, paint

BACK = "← Back to the menu"

COLUMNS = (
    Column("lane"),
    Column("state"),
    Column("pr"),
    Column("age", drop=1),
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
            value="improve",
            cells=(
                Cell("improve-lint-and-format-performance", lead="Acme.Widgets/"),
                Cell("no commits yet", tone="dim"),
                Cell("none", tone="dim"),
                Cell("today"),
            ),
            detail=("chore/improve-lint-and-format-performance",),
        ),
        Row(
            value="local",
            cells=(
                Cell("local-development-artifact-management", lead="Acme.Widgets/"),
                Cell("● 2 uncommitted", tone="warn"),
                Cell("#418 open", tone="warn"),
                Cell("today"),
            ),
            detail=("chore/local-development-artifact-management", "PR #418 open — http://x/418"),
        ),
    ]


def _browse(
    keys: PipeInput,
    sent: str,
    *,
    cursor: int = 0,
    columns: int = 120,
    rows: int = 40,
) -> tuple[str, int]:
    keys.send_text(sent)
    return browse(
        "2 open lanes",
        COLUMNS,
        _rows,
        BACK,
        cursor=cursor,
        input=keys,
        output=SizedOutput(columns, rows),
    )


def _lines(*, cursor: int = 0, width: int = 120, height: int = 40) -> list[str]:
    return paint(
        "2 open lanes", COLUMNS, _rows(), BACK, cursor=cursor, top=0, width=width, height=height
    ).lines


# -- choosing a row --------------------------------------------------------------


def test_enter_returns_the_row_under_the_cursor_and_where_it_was(keys: PipeInput) -> None:
    """The index comes back so an action can put the cursor where it left it."""
    assert _browse(keys, "\r") == ("improve", 0)


def test_the_arrows_move_the_cursor(keys: PipeInput) -> None:
    assert _browse(keys, "\x1b[B\r") == ("local", 1)


def test_moving_up_from_the_first_row_wraps_to_the_back_row(keys: PipeInput) -> None:
    """The picker wraps; so does this, and the last row is Back."""
    with pytest.raises(Abandoned):
        _browse(keys, "\x1b[A\r")


def test_home_and_end_jump_to_the_ends(keys: PipeInput) -> None:
    assert _browse(keys, "\x1b[B\x1b[H\r") == ("improve", 0)


def test_the_cursor_can_start_on_a_given_row(keys: PipeInput) -> None:
    assert _browse(keys, "\r", cursor=1) == ("local", 1)


def test_a_cursor_past_the_end_is_clamped(keys: PipeInput) -> None:
    """A row was closed while the cursor sat on the last one."""
    assert _browse(keys, "\r", cursor=9) == ("local", 1)


# -- going back ------------------------------------------------------------------


def test_the_back_row_is_last_and_choosing_it_abandons(keys: PipeInput) -> None:
    with pytest.raises(Abandoned):
        _browse(keys, "\x1b[F\r")


def test_the_back_row_is_drawn_after_every_lane() -> None:
    lines = _lines()
    assert lines[-1].strip() != BACK, "Back is a row, not the footer"
    positions = [index for index, line in enumerate(lines) if BACK in line]
    assert len(positions) == 1
    # `Acme.Widgets/` is a cell lead, so it marks table rows and nothing else.
    last_lane = max(index for index, line in enumerate(lines) if "Acme.Widgets/" in line)
    assert positions[0] > last_lane


def test_ctrl_c_abandons(keys: PipeInput) -> None:
    with pytest.raises(Abandoned):
        _browse(keys, "\x03")


def test_option_left_does_not_abandon(keys: PipeInput) -> None:
    """Escape is unbound here too, so Option+Arrow has nothing to trip over."""
    assert _browse(keys, "\x1b[1;3D\r") == ("improve", 0)


def test_an_unrecognised_key_is_ignored_and_the_table_stays_up(keys: PipeInput) -> None:
    assert _browse(keys, "cqz3\r") == ("improve", 0)


def test_an_unrecognised_key_does_not_disturb_the_cursor(keys: PipeInput) -> None:
    assert _browse(keys, "\x1b[Bc\r") == ("local", 1)


# -- what is drawn ----------------------------------------------------------------


def test_the_title_and_the_column_headers_are_drawn() -> None:
    lines = _lines()
    assert "2 open lanes" in lines[0]
    header = next(line for line in lines if "state" in line and "pr" in line)
    assert "lane" in header
    assert "age" in header


def test_the_cursor_marks_exactly_one_row() -> None:
    assert sum(line.startswith("❯") for line in _lines(cursor=1)) == 1
    assert next(line for line in _lines(cursor=1) if line.startswith("❯")).count("local-dev") == 1


def test_the_footer_is_the_pickers_own_wording() -> None:
    from lane.ui.picker import HINT

    assert HINT in _lines()[-1]


# -- the panel follows the cursor -------------------------------------------------


def test_the_panel_shows_the_row_under_the_cursor() -> None:
    body = "\n".join(_lines(cursor=0))
    assert "chore/improve-lint-and-format-performance" in body
    assert "chore/local-development-artifact-management" not in body


def test_the_panel_changes_with_the_cursor() -> None:
    body = "\n".join(_lines(cursor=1))
    assert "chore/local-development-artifact-management" in body
    assert "PR #418 open — http://x/418" in body
    assert "chore/improve-lint-and-format-performance" not in body


def test_the_back_row_has_no_panel() -> None:
    body = "\n".join(_lines(cursor=2))
    assert "chore/" not in body


# -- a narrow terminal ------------------------------------------------------------


def test_the_age_column_is_the_first_thing_dropped() -> None:
    lines = _lines(width=72)
    header = next(line for line in lines if "state" in line)
    assert "age" not in header
    assert "state" in header and "pr" in header


def test_the_project_prefix_goes_before_the_lane_name_is_touched() -> None:
    body = "\n".join(_lines(width=64))
    assert "Acme.Widgets/" not in body
    assert "improve-lint-and-format-performance" in body
    assert "no commits yet" in body


def test_the_lane_name_truncates_last_and_state_and_pr_never_do() -> None:
    lines = _lines(width=44)
    assert any("…" in line for line in lines), "the lane name gave way"
    body = "\n".join(lines)
    assert "no commits yet" in body
    assert "● 2 uncommitted" in body
    assert "#418 open" in body


def test_a_wide_terminal_keeps_everything() -> None:
    body = "\n".join(_lines(width=140))
    assert "Acme.Widgets/improve-lint-and-format-performance" in body
    assert "today" in body
    assert "…" not in body


def _rows_combined_state() -> list[Row[str]]:
    """The realistic combined state string, not the short placeholders above.

    `test_the_lane_name_truncates_last_and_state_and_pr_never_do` uses `"● 2
    uncommitted"` alone, which is short enough to survive at width 44 without any
    abbreviation kicking in — it never exercised the case that actually regressed.
    """
    return [
        Row(
            value="local",
            cells=(
                Cell("local-development-artifact-management", lead="Acme.Widgets/"),
                Cell("● 1 uncommitted · ↑ 1 unpushed", tone="warn", short="●1 ↑1"),
                Cell("#418 open", tone="warn"),
                Cell("today"),
            ),
            detail=("chore/local-development-artifact-management",),
        ),
    ]


def _combined_lines(*, width: int) -> list[str]:
    return paint(
        "1 open lane",
        COLUMNS,
        _rows_combined_state(),
        BACK,
        cursor=0,
        top=0,
        width=width,
        height=40,
    ).lines


@pytest.mark.parametrize("width", [40, 44])
def test_state_abbreviates_before_pr_is_ever_endangered(width: int) -> None:
    """L7: `state` shrinks to its `short` form; `pr` is never dropped or cut."""
    lines = _combined_lines(width=width)
    body = "\n".join(lines)
    assert "#418 open" in body, "pr must never be dropped"
    header = next(line for line in lines if "state" in line)
    assert "pr" in header, "the pr column itself must never be dropped"
    row = next(line for line in lines if "418" in line)
    assert len(row) <= width, "the row must actually fit the terminal"
    assert "●1 ↑1" in body, "state used its abbreviated form"
    assert "● 1 uncommitted" not in body, "the long form should not still be present"


# -- more rows than fit -----------------------------------------------------------


def _many(count: int) -> list[Row[str]]:
    return [
        Row(
            value=f"lane{index}",
            cells=(
                Cell(f"lane-number-{index}"),
                Cell("no commits yet"),
                Cell("none"),
                Cell("today"),
            ),
            detail=(f"chore/lane-number-{index}",),
        )
        for index in range(count)
    ]


def _many_lines(*, cursor: int, height: int, top: int = 0) -> list[str]:
    return paint(
        "14 open lanes", COLUMNS, _many(14), BACK, cursor=cursor, top=top, width=120, height=height
    ).lines


def test_only_a_window_of_rows_is_drawn_when_they_do_not_all_fit() -> None:
    drawn = [line for line in _many_lines(cursor=0, height=16) if "lane-number-" in line]
    assert 0 < len(drawn) < 14


def test_the_footer_says_which_rows_are_showing() -> None:
    footer = _many_lines(cursor=0, height=16)[-1]
    assert "of 14" in footer


def test_the_footer_says_nothing_about_a_range_when_everything_fits() -> None:
    assert "of 14" not in _many_lines(cursor=0, height=40)[-1]


def test_the_window_follows_the_cursor_down() -> None:
    body = "\n".join(_many_lines(cursor=13, height=16))
    assert "lane-number-13" in body
    assert "lane-number-0" not in body


def test_the_window_follows_the_cursor_back_up() -> None:
    body = "\n".join(_many_lines(cursor=0, height=16, top=9))
    assert "lane-number-0" in body


def test_the_back_row_is_reachable_by_scrolling() -> None:
    body = "\n".join(_many_lines(cursor=14, height=16))
    assert BACK in body


# -- a short terminal --------------------------------------------------------------


def test_the_panel_is_dropped_before_any_row_is() -> None:
    """The panel goes as soon as keeping it would push the table below three rows."""
    short = _many_lines(cursor=0, height=9)
    tall = _many_lines(cursor=0, height=20)
    assert any("chore/lane-number-0" in line for line in tall)
    assert not any("chore/lane-number-0" in line for line in short)
    assert len([line for line in short if "lane-number-" in line]) >= 3


def test_a_very_short_terminal_still_draws_a_row_and_the_footer() -> None:
    lines = _many_lines(cursor=0, height=7)
    assert any("lane-number-" in line for line in lines)
    from lane.ui.picker import HINT

    assert HINT in lines[-1]


# -- the slow column fills in ------------------------------------------------------


def test_the_first_paint_does_not_wait_for_the_fill(keys: PipeInput) -> None:
    """If browse waited on `fill`, this test would hang rather than fail."""
    forever = threading.Event()

    def fill(notify: object) -> None:
        del notify
        forever.wait(30)

    keys.send_text("\r")
    try:
        chosen = browse(
            "2 open lanes",
            COLUMNS,
            _rows,
            BACK,
            fill=fill,
            input=keys,
            output=SizedOutput(),
        )
    finally:
        forever.set()

    assert chosen == ("improve", 0)


def test_a_filled_in_cell_is_repainted(keys: PipeInput) -> None:
    """The pending cell is on screen first, and the answer replaces it."""
    pending = {"value": True}
    painted: list[str] = []
    first_paint = threading.Event()
    filled_paint = threading.Event()

    def rows() -> list[Row[str]]:
        cell = Cell("checking…", tone="dim") if pending["value"] else Cell("#418 open", tone="warn")
        return [
            Row(value="one", cells=(Cell("a-lane"), Cell("no commits yet"), cell, Cell("today")))
        ]

    def watch(line: str) -> None:
        painted.append(line)
        first_paint.set()
        if "#418 open" in line:
            filled_paint.set()

    def fill(notify: object) -> None:
        assert callable(notify)
        # Deliberately after the first paint: this asserts the order, not a sleep.
        first_paint.wait(30)
        pending["value"] = False
        notify()
        filled_paint.wait(30)
        keys.send_text("\r")

    browse(
        "1 open lane",
        COLUMNS,
        rows,
        BACK,
        fill=fill,
        input=keys,
        output=SizedOutput(),
        on_render=watch,
    )

    assert any("checking…" in line for line in painted), "the pending cell was drawn"
    assert any("#418 open" in line for line in painted), "and then replaced"


# -- no rows at all ----------------------------------------------------------------


def test_a_table_with_no_rows_is_only_a_way_back(keys: PipeInput) -> None:
    """The listing never gets here — it says "no open lanes" and returns."""
    keys.send_text("\r")
    with pytest.raises(Abandoned):
        browse("nothing", COLUMNS, list, BACK, input=keys, output=SizedOutput())
