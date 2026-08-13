"""The interactive table: a cursor over rows, and the row under it is the subject.

This is the listing's widget, and it sits **below** the `Ui` seam for the same
reason the picker does — a component with its own tests, driven through
`prompt_toolkit`'s pipe input. See ADR 0002 for why the listing is one screen
rather than a table followed by a second prompt that re-lists everything.

## It introduces no keys

| Key | |
|---|---|
| `↑` `↓` `Home` `End` | move |
| `Enter` | choose the row under the cursor |
| `Ctrl-C` | back out |

That is the picker's binding set exactly, and it is deliberate: a letter key for
"close" would be this tool's invention, in the same class as the `q`, `j`/`k` and
digit shortcuts AGENTS.md removed. Choosing a row opens a two-entry menu instead,
which costs a keystroke and no new vocabulary. Going back is a **visible row** at
the end of the table, not a key — as everywhere else.

A screen whose rows each carry their own answer is **not** this widget: it is
`checklist.py`, which binds `Space`, draws a tree one level at a time, and where `Enter`
accepts the level rather than acting on the row unless the row is a folder to open. That
is a separate component for exactly those reasons.

## Layout gives the room to the columns that answer the question

The listing exists to answer "which of these can I close, and what is stopping the
ones that cannot", so `state` and `pr` are never dropped and never truncated. What
gives way, in order: whole columns by `Column.drop`, then the dim `Cell.lead` (a
project name repeated down the column), then the first column truncates. Vertically
the panel goes before any row does.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

from lane.ui.picker import ESCAPE_TIMEOUT, HINT
from lane.ui.seam import Abandoned, Cell, Column, Fill, Row

CURSOR_WIDTH = 2
"""The `❯ ` in front of the row under the cursor, and the space in front of the rest."""

MARK_WIDTH = 2
"""A second gutter, for a widget whose rows carry a mark — `checklist.py`'s `✓`/`◐`.

Here rather than there because `fit` has to know how much room the prefix takes
before it can decide which columns survive, and there is one such calculation.
"""

GAP = 2
MIN_FIRST_COLUMN = 12
MIN_VISIBLE_ROWS = 3
MAX_DETAIL_LINES = 3

STYLE = Style.from_dict(
    {
        "table.title": "bold",
        "table.header": "#8a8a8a",
        "table.pointer": "#00afff bold",
        "table.selected": "#00afff bold",
        "table.lead": "#8a8a8a",
        "table.dim": "#8a8a8a",
        "table.good": "#00af5f",
        "table.warn": "#d7875f",
        "table.bad": "#d75f5f",
        "table.panel": "#8a8a8a",
        "table.footer": "#8a8a8a",
    }
)

TONES = {
    "": "",
    "good": "class:table.good",
    "warn": "class:table.warn",
    "bad": "class:table.bad",
    "dim": "class:table.dim",
}


@dataclass(frozen=True, slots=True)
class Painted:
    """One frame: the fragments to draw, and the window they were drawn from."""

    fragments: list[tuple[str, str]]
    top: int
    """The first row of the window, adjusted so the cursor is inside it."""

    room: int
    """How many rows the window holds."""

    @property
    def lines(self) -> list[str]:
        return "".join(text for _, text in self.fragments).split("\n")


def clip(text: str, width: int) -> str:
    """Truncate with an ellipsis, so a cut is never mistaken for the real name."""
    if len(text) <= width:
        return text
    if width <= 1:
        return "…"[:width]
    return text[: width - 1] + "…"


def fit(
    columns: Sequence[Column],
    rows: Sequence[Row[object]],
    width: int,
    prefix: int = CURSOR_WIDTH,
) -> tuple[list[int], list[int], bool, bool]:
    """Which columns survive this width, how wide each is, and two switches.

    Returns `(kept column indexes, their widths, keep leads, use short cells)`.

    `prefix` is what the row's gutters cost before any column is drawn — the cursor,
    plus a mark where the widget has one. Shared so that a second widget cannot
    arrive at a different answer about the same terminal.
    """
    kept = list(range(len(columns)))
    leads = True
    short = False

    def widths(kept: list[int], leads: bool, short: bool) -> list[int]:
        return [
            max(
                [len(columns[index].title)]
                + [len(_shown(row.cells[index], leads, short)) for row in rows]
            )
            for index in kept
        ]

    def total(measured: list[int]) -> int:
        if not measured:
            return prefix
        return prefix + sum(measured) + GAP * (len(measured) - 1)

    measured = widths(kept, leads, short)

    # 1) Whole columns, least important first. `age` before anything else.
    while total(measured) > width:
        droppable = [index for index in kept if columns[index].drop > 0]
        if not droppable:
            break
        kept.remove(max(droppable, key=lambda index: (columns[index].drop, index)))
        measured = widths(kept, leads, short)

    # 2) The repeated project prefix, which identifies nothing on its own.
    if total(measured) > width and leads:
        leads = False
        measured = widths(kept, leads, short)

    # 3) `state`/`pr` cells switch to their abbreviated form, if they have one —
    # before the name is touched, so a long combined state doesn't force `pr` off
    # the edge of the screen (L7).
    if total(measured) > width and not short:
        short = True
        measured = widths(kept, leads, short)

    # 4) Only now the name itself, and never `state` or `pr`.
    if measured and total(measured) > width:
        measured[0] = max(MIN_FIRST_COLUMN, measured[0] - (total(measured) - width))

    return kept, measured, leads, short


def _shown(cell: Cell, leads: bool, short: bool = False) -> str:
    text = cell.short if short and cell.short else cell.text
    return f"{cell.lead}{text}" if leads else text


def row_fragments(
    row: Row[object],
    kept: Sequence[int],
    measured: Sequence[int],
    leads: bool,
    short: bool,
    *,
    selected: bool,
    mark: tuple[str, str] | None = None,
) -> list[tuple[str, str]]:
    """One row, gutters included. `mark` is a second gutter — see `MARK_WIDTH`."""
    fragments: list[tuple[str, str]] = [("class:table.pointer", "❯ " if selected else "  ")]
    if mark is not None:
        fragments.append(mark)
    for position, (index, column_width) in enumerate(zip(kept, measured, strict=True)):
        cell = row.cells[index]
        last = position == len(kept) - 1
        style = "class:table.selected" if selected and position == 0 else TONES[cell.tone]

        lead = cell.lead if leads else ""
        cell_text = cell.short if short and cell.short else cell.text
        text = clip(f"{lead}{cell_text}", column_width)
        if lead and text.startswith(lead):
            fragments.append(("class:table.lead", lead))
            fragments.append((style, text[len(lead) :]))
        else:
            fragments.append((style, text))

        padding = column_width - len(text) + (0 if last else GAP)
        if padding > 0 and not last:
            fragments.append(("", " " * padding))
    fragments.append(("", "\n"))
    return fragments


def window(total: int, cursor: int, top: int, room: int) -> int:
    """Scroll only as far as it takes to keep the cursor on screen."""
    if total <= room:
        return 0
    if cursor < top:
        top = cursor
    elif cursor >= top + room:
        top = cursor - room + 1
    return max(0, min(top, total - room))


def paint(
    title: str,
    columns: Sequence[Column],
    rows: Sequence[Row[object]],
    back: str,
    *,
    cursor: int,
    top: int,
    width: int,
    height: int,
) -> Painted:
    """Draw one frame. Pure, which is what makes the layout rules testable."""
    total = len(rows) + 1  # the visible way back is a row like any other
    cursor = max(0, min(cursor, total - 1))
    on_back = cursor == len(rows)

    wanted = () if on_back else rows[cursor].detail[:MAX_DETAIL_LINES]
    room, detail = vertical(height, wanted)
    top = window(total, cursor, top, room)

    kept, measured, leads, short = fit(columns, rows, width)

    fragments: list[tuple[str, str]] = [("class:table.title", f"  {title}"), ("", "\n\n")]

    if kept and rows:
        header = "  " + "".join(
            columns[index].title.ljust(column_width + GAP)
            for index, column_width in zip(kept, measured, strict=True)
        )
        fragments.append(("class:table.header", header.rstrip()))
        fragments.append(("", "\n"))

    for position in range(top, min(top + room, total)):
        if position == len(rows):
            selected = on_back
            fragments.append(("class:table.pointer", "❯ " if selected else "  "))
            fragments.append(("class:table.selected" if selected else "", back))
            fragments.append(("", "\n"))
            continue
        fragments += row_fragments(
            rows[position], kept, measured, leads, short, selected=position == cursor
        )

    fragments.append(("", "\n"))
    for line in detail:
        fragments.append(("class:table.panel", f"  {clip(line, width - 2)}"))
        fragments.append(("", "\n"))
    if detail:
        fragments.append(("", "\n"))

    shown = ""
    if total > room:
        first = top + 1
        last = min(top + room, total)
        shown = f" · {first}–{last} of {len(rows)}"
    fragments.append(("class:table.footer", f"  {HINT}{shown}"))

    return Painted(fragments=fragments, top=top, room=room)


def vertical(height: int, detail: tuple[str, ...], extra: int = 0) -> tuple[int, tuple[str, ...]]:
    """How many rows fit, and whether the panel survives.

    The panel is dropped before any row is: the table answers the questions and the
    panel only elaborates on one of them.

    `extra` is any further fixed line a widget draws below the panel — the
    checklist's running count of what is in.
    """
    # title, blank, header, blank before the panel, blank after it, footer.
    for lines in (len(detail), 0):
        overhead = (6 + lines if lines else 5) + extra
        room = height - overhead
        if room >= MIN_VISIBLE_ROWS:
            return room, (detail if lines else ())
    return max(1, height - 5 - extra), ()


def bindings_for[T](
    state: dict[str, int],
    rows: Callable[[], Sequence[Row[T]]],
    exit_with: Callable[[tuple[T, int] | None], None],
) -> KeyBindings:
    """The keys this table answers to: **the picker's set, and nothing else, ever.**

    A unit of its own so that "this table binds no key of its own" is something a test can
    *check* rather than something the docs assert: a bound handler that happens to do
    nothing looks identical from the outside while still swallowing the keystroke.

    A screen whose rows each carry an answer is not this widget: it is `checklist.py`,
    which binds `Space` and is a different component for exactly that reason.
    """
    bindings = KeyBindings()

    def last() -> int:
        return state["rows"]  # the back row sits one past the last lane

    def under_cursor() -> Row[T] | None:
        current = list(rows())
        index = state["index"]
        return current[index] if index < len(current) else None

    @bindings.add("c-c")
    def _abandon(event: KeyPressEvent) -> None:
        del event
        exit_with(None)

    @bindings.add("up")
    def _up(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] - 1) % (last() + 1)

    @bindings.add("down")
    def _down(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] + 1) % (last() + 1)

    @bindings.add("home")
    def _first(event: KeyPressEvent) -> None:
        del event
        state["index"] = 0

    @bindings.add("end")
    def _end(event: KeyPressEvent) -> None:
        del event
        state["index"] = last()

    @bindings.add("enter")
    def _accept(event: KeyPressEvent) -> None:
        del event
        row = under_cursor()
        if row is None:
            # The back row, one past the last: the same result as Ctrl-C.
            exit_with(None)
            return
        exit_with((row.value, state["index"]))

    return bindings


def browse[T](
    title: str,
    columns: Sequence[Column],
    rows: Callable[[], Sequence[Row[T]]],
    back: str,
    *,
    fill: Fill | None = None,
    cursor: int = 0,
    on_render: Callable[[str], None] | None = None,
    input: Input | None = None,
    output: Output | None = None,
) -> tuple[T, int]:
    """The row the cursor was on when Enter was pressed, and its index.

    Raises `Abandoned` for the visible back row and for Ctrl-C — the two ways out
    mean the same thing to the caller, so they are the same result.
    """
    state = {"index": max(0, cursor), "top": 0, "rows": 0, "opening": 1}

    def render() -> FormattedText:
        current = list(rows())
        state["rows"] = len(current)
        if state["opening"]:
            # A lane was closed while the cursor sat on the last row, so the index
            # handed back is now past the end. Land on the row that took its place
            # rather than on the way out.
            state["opening"] = 0
            state["index"] = min(state["index"], max(0, len(current) - 1))
        state["index"] = max(0, min(state["index"], len(current)))
        size = application.output.get_size()
        painted = paint(
            title,
            columns,
            current,
            back,
            cursor=state["index"],
            top=state["top"],
            width=size.columns,
            height=size.rows - 1,
        )
        state["top"] = painted.top
        if on_render is not None:
            for line in painted.lines:
                on_render(line)
        return FormattedText(painted.fragments)

    bindings = bindings_for(
        state,
        rows,
        # Deferred rather than passed: `application.exit` does not exist until the
        # Application below has been built, and by then these handlers are only defined.
        lambda result: application.exit(result=result),
    )

    application: Application[object] = Application(
        layout=Layout(
            HSplit(
                [
                    Window(
                        # As in the picker: without this the terminal cursor parks
                        # on the first character and reads as if it were selected.
                        FormattedTextControl(render, show_cursor=False),
                        dont_extend_height=True,
                    )
                ]
            )
        ),
        key_bindings=bindings,
        style=STYLE,
        full_screen=False,
        erase_when_done=True,
        input=input,
        output=output,
    )
    application.ttimeoutlen = ESCAPE_TIMEOUT

    if fill is not None:
        # On a thread, so the first paint never waits for a `gh` round trip.
        # `Application.invalidate` is documented thread-safe and no-ops before the
        # application is running, which is harmless: `rows()` is read on every
        # repaint, so an early answer is simply on screen from the first frame.
        threading.Thread(target=fill, args=(application.invalidate,), daemon=True).start()

    result = application.run()
    if result is None:
        raise Abandoned
    return result  # type: ignore[return-value]
