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

from lane.ui.picker import ESCAPE_TIMEOUT, HINT, TOGGLE_HINT
from lane.ui.seam import Abandoned, Cell, Column, Fill, Row, Toggle

CURSOR_WIDTH = 2
"""The `❯ ` in front of the row under the cursor, and the space in front of the rest."""

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

_TONES = {
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


def _clip(text: str, width: int) -> str:
    """Truncate with an ellipsis, so a cut is never mistaken for the real name."""
    if len(text) <= width:
        return text
    if width <= 1:
        return "…"[:width]
    return text[: width - 1] + "…"


def _fit(
    columns: Sequence[Column],
    rows: Sequence[Row[object]],
    width: int,
) -> tuple[list[int], list[int], bool, bool]:
    """Which columns survive this width, how wide each is, and two switches.

    Returns `(kept column indexes, their widths, keep leads, use short cells)`.
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
            return CURSOR_WIDTH
        return CURSOR_WIDTH + sum(measured) + GAP * (len(measured) - 1)

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


def _row_fragments(
    row: Row[object],
    kept: Sequence[int],
    measured: Sequence[int],
    leads: bool,
    short: bool,
    *,
    selected: bool,
) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = [("class:table.pointer", "❯ " if selected else "  ")]
    for position, (index, column_width) in enumerate(zip(kept, measured, strict=True)):
        cell = row.cells[index]
        last = position == len(kept) - 1
        style = "class:table.selected" if selected and position == 0 else _TONES[cell.tone]

        lead = cell.lead if leads else ""
        cell_text = cell.short if short and cell.short else cell.text
        text = _clip(f"{lead}{cell_text}", column_width)
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


def _window(total: int, cursor: int, top: int, room: int) -> int:
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
    toggles: bool = False,
) -> Painted:
    """Draw one frame. Pure, which is what makes the layout rules testable."""
    total = len(rows) + 1  # the visible way back is a row like any other
    cursor = max(0, min(cursor, total - 1))
    on_back = cursor == len(rows)

    wanted = () if on_back else rows[cursor].detail[:MAX_DETAIL_LINES]
    room, detail = _vertical(height, wanted)
    top = _window(total, cursor, top, room)

    kept, measured, leads, short = _fit(columns, rows, width)

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
        fragments += _row_fragments(
            rows[position], kept, measured, leads, short, selected=position == cursor
        )

    fragments.append(("", "\n"))
    for line in detail:
        fragments.append(("class:table.panel", f"  {_clip(line, width - 2)}"))
        fragments.append(("", "\n"))
    if detail:
        fragments.append(("", "\n"))

    shown = ""
    if total > room:
        first = top + 1
        last = min(top + room, total)
        shown = f" · {first}–{last} of {len(rows)}"
    hint = TOGGLE_HINT if toggles else HINT
    fragments.append(("class:table.footer", f"  {hint}{shown}"))

    return Painted(fragments=fragments, top=top, room=room)


def _vertical(height: int, detail: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
    """How many rows fit, and whether the panel survives.

    The panel is dropped before any row is: the table answers the questions and the
    panel only elaborates on one of them.
    """
    # title, blank, header, blank before the panel, blank after it, footer.
    for lines in (len(detail), 0):
        overhead = 6 + lines if lines else 5
        room = height - overhead
        if room >= MIN_VISIBLE_ROWS:
            return room, (detail if lines else ())
    return max(1, height - 5), ()


def browse[T](
    title: str,
    columns: Sequence[Column],
    rows: Callable[[], Sequence[Row[T]]],
    back: str,
    *,
    fill: Fill | None = None,
    cursor: int = 0,
    toggle: Toggle[T] | None = None,
    on_render: Callable[[str], None] | None = None,
    input: Input | None = None,
    output: Output | None = None,
) -> tuple[T, int]:
    """The row the cursor was on when Enter was pressed, and its index.

    Raises `Abandoned` for the visible back row and for Ctrl-C — the two ways out
    mean the same thing to the caller, so they are the same result.

    With a `toggle`, rows carry an answer that is changed in place: `Space` changes the
    row under the cursor and the table stays up. `Enter` calls the same `toggle` and
    only returns the row when it says it does not toggle — one code path, so `Enter`
    cannot drift from `Space`.
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
            toggles=toggle is not None,
        )
        state["top"] = painted.top
        if on_render is not None:
            for line in painted.lines:
                on_render(line)
        return FormattedText(painted.fragments)

    bindings = KeyBindings()

    def _last() -> int:
        return state["rows"]  # the back row sits one past the last lane

    @bindings.add("c-c")
    def _abandon(event: KeyPressEvent) -> None:
        del event
        application.exit(result=None)

    @bindings.add("up")
    def _up(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] - 1) % (_last() + 1)

    @bindings.add("down")
    def _down(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] + 1) % (_last() + 1)

    @bindings.add("home")
    def _first(event: KeyPressEvent) -> None:
        del event
        state["index"] = 0

    @bindings.add("end")
    def _end(event: KeyPressEvent) -> None:
        del event
        state["index"] = _last()

    def _under_cursor() -> Row[T] | None:
        current = list(rows())
        index = state["index"]
        return current[index] if index < len(current) else None

    @bindings.add(" ")
    def _change(event: KeyPressEvent) -> None:
        del event
        row = _under_cursor()
        if toggle is not None and row is not None:
            # The answer belongs to the caller, as the rows already do. Whatever it
            # changed is on screen at the next repaint, which `rows()` supplies.
            toggle(row.value)

    @bindings.add("enter")
    def _accept(event: KeyPressEvent) -> None:
        del event
        row = _under_cursor()
        if row is None:
            # The back row, one past the last: the same result as Ctrl-C.
            application.exit(result=None)
            return
        if toggle is not None and toggle(row.value):
            # A row that carries an answer: Enter changed it, and there is more to do
            # on this screen. Exactly what Space just did, by the same call.
            return
        application.exit(result=(row.value, state["index"]))

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
