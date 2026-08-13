"""A list of rows, each in or out, changed under the cursor with one keystroke.

The table's layout with a tick in front of every row, and the one screen in lane
whose rows carry a two-state answer. It sits **below** the `Ui` seam for the same
reason the picker and the table do — a component with its own tests, driven through
`prompt_toolkit`'s pipe input.

## It binds one key the rest of lane does not

| Key | |
|---|---|
| `↑` `↓` `Home` `End` | move |
| `Space` | tick the row under the cursor, or untick it |
| `Enter` | accept the screen |
| `Ctrl-C` | back out |

`Space` is the addition, and `Enter` means something different here than it does in
the lanes table, where it acts on the row. Both were decided deliberately rather
than slipped in (AGENTS.md, *Going back is visible*): this is the universal
multi-select convention, it is what makes a dozen answers a dozen keystrokes, and a
screen where `Enter` acted on the row would need a second key to accept — which is
the vocabulary this one is spending its budget on.

There is no `← Back` row. A checklist has nothing to choose between, so the way out
is a footer hint, exactly as `text` and `confirm` do it (docs/CONVENTIONS.md §2).

## Why not prompt_toolkit's `CheckboxList`

It draws every option into one window with no scrolling of its own — the defect
AGENTS.md already measured on `picker.pick`, where 300 branches became 304 lines
with the cursor walking off the bottom of the terminal. It also has no columns, no
dim lead, no cursor panel, and no way to let a slow column land behind the first
paint. All four are things this screen needs, and all four the table already has.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import Output

from lane.ui.picker import ESCAPE_TIMEOUT
from lane.ui.seam import Abandoned, Column, Fill, Row
from lane.ui.table import (
    CURSOR_WIDTH,
    GAP,
    MARK_WIDTH,
    MAX_DETAIL_LINES,
    STYLE,
    Painted,
    clip,
    fit,
    row_fragments,
    vertical,
    window,
)

HINT = "↑↓ move · space toggle · enter accept · ctrl-c back out"
"""One hint per widget, not one per call site (docs/CONVENTIONS.md §2). It names
`space` because `space` is the key this screen adds, and `enter` because `enter` means
something different here; the table's hint names neither, because the table adds none."""

HINTS = (
    HINT,
    "space toggle · enter accept · ctrl-c back out",
    "space · enter · ctrl-c back out",
)
"""The hint, and what it becomes on a terminal too narrow for it.

§2 requires the one way out to be *visible*, and a hint clipped to `ctr…` is not. So it
gives things up in the order they can be spared: the arrows first, because nobody needs
telling that arrows move; then what each key *does*, because the keys themselves are the
part that has to survive. `ctrl-c back out` is never shortened — it is the only thing on
the screen that says how to leave.
"""

TICK = "✓ "
"""`✓` already means *this is fine* elsewhere; here it means *this one is in*. Same
symbol, no new one — and the meaning is carried by the tick's presence rather than
by its colour (docs/CONVENTIONS.md §5, §6)."""

BLANK = "  "

SUMMARY_LINES = 1
"""The running count sits between the panel and the footer, always drawn."""

_MARK_STYLE = "class:table.good"


def paint(
    title: str,
    columns: Sequence[Column],
    rows: Sequence[Row[object]],
    *,
    checked: frozenset[object],
    cursor: int,
    top: int,
    width: int,
    height: int,
    summary: str = "",
) -> Painted:
    """Draw one frame. Pure, which is what makes the layout rules testable."""
    total = len(rows)
    cursor = max(0, min(cursor, total - 1)) if total else 0

    wanted = rows[cursor].detail[:MAX_DETAIL_LINES] if total else ()
    room, detail = vertical(height, wanted, extra=SUMMARY_LINES)
    top = window(total, cursor, top, room)

    prefix = CURSOR_WIDTH + MARK_WIDTH
    kept, measured, leads, short = fit(columns, rows, width, prefix)

    fragments: list[tuple[str, str]] = [("class:table.title", f"  {title}"), ("", "\n\n")]

    if kept and rows:
        header = " " * prefix + "".join(
            columns[index].title.ljust(column_width + GAP)
            for index, column_width in zip(kept, measured, strict=True)
        )
        fragments.append(("class:table.header", header.rstrip()))
        fragments.append(("", "\n"))

    for position in range(top, min(top + room, total)):
        row = rows[position]
        mark = TICK if row.value in checked else BLANK
        fragments += row_fragments(
            row,
            kept,
            measured,
            leads,
            short,
            selected=position == cursor,
            mark=(_MARK_STYLE, mark),
        )

    fragments.append(("", "\n"))
    for line in detail:
        fragments.append(("class:table.panel", f"  {clip(line, width - 2)}"))
        fragments.append(("", "\n"))
    if detail:
        fragments.append(("", "\n"))

    counted = tally(len(checked), total)
    if summary:
        counted = f"{counted} · {summary}"
    fragments.append(("class:table.panel", f"  {clip(counted, width - 2)}"))
    fragments.append(("", "\n"))

    shown = ""
    if total > room:
        shown = f" · {top + 1}–{min(top + room, total)} of {total}"
    fragments.append(("class:table.footer", f"  {clip(footer(width - 2, shown), width - 2)}"))

    return Painted(fragments=fragments, top=top, room=room)


def footer(width: int, shown: str = "") -> str:
    """The longest hint that fits, with the scroll position where there is room for it.

    The position goes before any of the hint does: `1–19 of 40` is a convenience, and the
    hint is the only thing on screen saying how to leave.
    """
    for hint in HINTS:
        for whole in (hint + shown, hint):
            if len(whole) <= width:
                return whole
    return HINTS[-1]


def tally(count: int, total: int) -> str:
    """What the screen has decided so far, in one line.

    Worth a line of its own because the rows do not all fit: a folder of forty loose
    files scrolls, and without this the only way to know how many are in is to scroll
    back through them. `nothing in yet` rather than `0 of 3 in` — a count of zero is
    the one case where the number reads as an error rather than an answer.
    """
    if not count:
        return "nothing in yet"
    return f"{count} of {total} in"


def bindings_for[T](
    state: dict[str, int],
    rows: Callable[[], Sequence[Row[T]]],
    checked: set[T],
    exit_with: Callable[[frozenset[T] | None], None],
) -> KeyBindings:
    """The keys this checklist answers to: the picker's set, plus `Space`.

    A unit of its own so that "this widget binds exactly one key beyond the picker's"
    is something a test can *check* rather than something the docs assert.
    """
    bindings = KeyBindings()

    def count() -> int:
        return max(1, state["rows"])

    @bindings.add("c-c")
    def _abandon(event: KeyPressEvent) -> None:
        del event
        exit_with(None)

    @bindings.add("up")
    def _up(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] - 1) % count()

    @bindings.add("down")
    def _down(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] + 1) % count()

    @bindings.add("home")
    def _first(event: KeyPressEvent) -> None:
        del event
        state["index"] = 0

    @bindings.add("end")
    def _end(event: KeyPressEvent) -> None:
        del event
        state["index"] = max(0, state["rows"] - 1)

    @bindings.add("space")
    def _toggle(event: KeyPressEvent) -> None:
        del event
        current = list(rows())
        index = state["index"]
        if index >= len(current):
            return
        value = current[index].value
        # The cursor does not move. "The answer changes under the cursor, in place"
        # is the whole requirement, and a list that advances on toggle makes
        # correcting the row you just ticked a two-key job.
        if value in checked:
            checked.discard(value)
        else:
            checked.add(value)

    @bindings.add("enter")
    def _accept(event: KeyPressEvent) -> None:
        del event
        exit_with(frozenset(checked))

    return bindings


def check[T](
    title: str,
    columns: Sequence[Column],
    rows: Callable[[], Sequence[Row[T]]],
    *,
    checked: Iterable[T] = (),
    summary: Callable[[frozenset[T]], str] | None = None,
    fill: Fill | None = None,
    on_render: Callable[[str], None] | None = None,
    input: Input | None = None,
    output: Output | None = None,
) -> frozenset[T]:
    """Everything ticked when `Enter` was pressed. `Ctrl-C` raises `Abandoned`.

    The ticks are the widget's own, unlike the table's `rows`: in-or-out is the whole
    of what this screen records, so there is nothing about what an answer *means*
    below the seam to keep out of it.

    `summary` is the caller's half of the running count — *how much* is coming in,
    which only the action knows, beside the widget's *how many*.
    """
    ticked: set[T] = set(checked)
    state = {"index": 0, "top": 0, "rows": 0}

    def render() -> FormattedText:
        current = list(rows())
        state["rows"] = len(current)
        state["index"] = max(0, min(state["index"], max(0, len(current) - 1)))
        size = application.output.get_size()
        settled = frozenset(ticked)
        painted = paint(
            title,
            columns,
            current,
            checked=settled,
            cursor=state["index"],
            top=state["top"],
            width=size.columns,
            height=size.rows - 1,
            summary=summary(settled) if summary is not None else "",
        )
        state["top"] = painted.top
        if on_render is not None:
            for line in painted.lines:
                on_render(line)
        return FormattedText(painted.fragments)

    bindings = bindings_for(
        state,
        rows,
        ticked,
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
        # On a thread, so the first paint never waits for `du` on a large tree.
        threading.Thread(target=fill, args=(application.invalidate,), daemon=True).start()

    result = application.run()
    if result is None:
        raise Abandoned
    return result  # type: ignore[return-value]
