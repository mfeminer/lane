"""L6: a `rich`-rendered word that overflows degrades like the lanes table does —
a single-line ellipsis, never `rich`'s default of folding mid-word across two.
"""

from __future__ import annotations

from rich.console import Console

from lane.ui.console_ui import ConsoleUi
from lane.ui.seam import Cell, Column, Row


def test_a_long_path_is_truncated_with_an_ellipsis_instead_of_wrapped() -> None:
    console = Console(width=20, record=True, highlight=False)
    ui = ConsoleUi(console=console)

    long_path = "/private/tmp/claude-501/some-long-scratchpad-directory/session/file.txt"
    ui.info(f"Running: {long_path}")

    lines = console.export_text().splitlines()
    non_blank = [line for line in lines if line.strip()]
    # The path is clipped as one whole word, so it may still wrap onto its own line
    # after "Running:" (ordinary word-wrap) — what must never happen is the word
    # itself being split mid-character across two lines, which is the original bug:
    # exactly one line carries (any part of) the path, and it ends in an ellipsis.
    path_lines = [line for line in non_blank if line.strip().startswith("/private")]
    assert len(path_lines) == 1
    assert path_lines[0].strip().endswith("…")


def test_ordinary_prose_still_wraps_at_its_spaces_instead_of_being_clipped() -> None:
    """The path fix above must not stop a long *sentence* from wrapping normally —
    only a single overlong word (a path) should ever be clipped."""
    console = Console(width=20, record=True, highlight=False)
    ui = ConsoleUi(console=console)

    prose = "Open a lane per task: its own worktree, branch and editor window."
    ui.detail(prose)

    lines = console.export_text().splitlines()
    non_blank = [line for line in lines if line.strip()]
    assert len(non_blank) > 1, "a long sentence should wrap across lines, not clip to one"
    assert not any(line.rstrip().endswith("…") for line in non_blank)
    assert " ".join(line.strip() for line in non_blank) == prose


# -- the printed table -------------------------------------------------------------
# `lane list` is read-only and works in a pipe, so it prints rather than opening the
# screen you stand in. What it must not do is draw its own table: these pin it to the
# lanes table's layout rules, which is the only reason a second renderer is allowed
# to exist at all.


def test_a_printed_table_carries_its_title_its_header_and_every_row() -> None:
    console = Console(width=60, record=True, highlight=False)
    ui = ConsoleUi(console=console)

    ui.table(
        "2 open lanes in demo",
        (Column("lane"), Column("state"), Column("age", drop=1)),
        [
            Row(value=None, cells=(Cell("pager"), Cell("✓ merged"), Cell("today"))),
            Row(value=None, cells=(Cell("login"), Cell("● 2 uncommitted"), Cell("yesterday"))),
        ],
    )

    text = console.export_text()
    assert "2 open lanes in demo" in text
    assert "lane" in text
    assert "state" in text
    assert "pager" in text
    assert "● 2 uncommitted" in text


def test_a_printed_table_drops_the_droppable_column_first_at_a_narrow_width() -> None:
    """The same order of giving way the table has (§13): `age` goes, `state` never."""
    row = Row(value=None, cells=(Cell("pager"), Cell("● 2 uncommitted", short="●2"), Cell("today")))
    columns = (Column("lane"), Column("state"), Column("age", drop=1))

    console = Console(width=28, record=True, highlight=False)
    ConsoleUi(console=console).table("2 open lanes in demo", columns, [row])

    text = console.export_text()
    assert "today" not in text, "`age` is the column that gives way first"
    assert "● 2 uncommitted" in text, "and `state` is still whole at this width"

    narrower = Console(width=18, record=True, highlight=False)
    ConsoleUi(console=narrower).table("2 open lanes in demo", columns, [row])

    squeezed = narrower.export_text()
    assert "●2" in squeezed, "`state` abbreviates rather than being dropped or cut"
    assert "pager" in squeezed
