"""A tree of rows, each in or out, changed under the cursor with one keystroke.

The table's layout with a mark in front of every row, and the one screen in lane
whose rows carry their own answer. It sits **below** the `Ui` seam for the same
reason the picker and the table do — a component with its own tests, driven through
`prompt_toolkit`'s pipe input.

## One level of the tree per screen

Two hundred ignored paths drawn flat is not a screen, it is an ordeal, so the rows
are the branching points and a folder is something you go **into**: the same "you
stand in it and act on it" screen the lanes table is, one level at a time, with a
visible `← Back` row exactly as everywhere else. A folder's mark is three-state,
because it stands for every leaf beneath it and those can be all in, all out, or a
mix — `◐` (docs/CONVENTIONS.md §5). A leaf keeps the two it always had.

## It binds one key the rest of lane does not

| Key | |
|---|---|
| `↑` `↓` `Home` `End` | move |
| `Space` | answer the row under the cursor — a leaf, or every leaf under a folder |
| `Enter` | open the folder under the cursor; anywhere else accept the level you are in |
| `Ctrl-C` | back out |

`Space` is the addition, and it was decided deliberately rather than slipped in
(AGENTS.md, *Going back is visible*): this is the universal multi-select convention,
it is what makes a dozen answers a dozen keystrokes, and a screen where `Enter`
answered the row would need a second key to accept — which is the vocabulary this one
is spending its budget on.

**`Enter` opens the row if it opens, and otherwise accepts the level you are standing
in** — which at the root is the screen, exactly what it has always meant here, and
inside a folder is that folder, so a stray press cannot end preparation from three
levels down. The footer names whichever of the two applies to the row under the
cursor, because a screen says what its keys do.

The root has no `← Back` row: it is the level with nothing above it, so its way out is
the footer hint, exactly as `text` and `confirm` do it (docs/CONVENTIONS.md §2). Every
level inside a folder has one, because it has somewhere to go back to.

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
from lane.ui.seam import BACK_LABEL, Abandoned, Column, Fill, Node
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

ACCEPT, OPEN, UP = "accept", "open", "go up"
"""What `Enter` does to the row under the cursor, in the footer's words."""


def hints(action: str = ACCEPT) -> tuple[str, ...]:
    """The hint, and what it becomes on a terminal too narrow for it.

    One hint per widget, not one per call site (docs/CONVENTIONS.md §2). It names
    `space` because `space` is the key this screen adds, and `enter` because `enter`
    means something different here; the table's hint names neither, because the table
    adds none.

    §2 requires the one way out to be *visible*, and a hint clipped to `ctr…` is not. So
    it gives things up in the order they can be spared: the arrows first, because nobody
    needs telling that arrows move; then what each key *does*, because the keys
    themselves are the part that has to survive. `ctrl-c back out` is never shortened —
    it is the only thing on the screen that says how to leave.
    """
    return (
        f"↑↓ move · space toggle · enter {action} · ctrl-c back out",
        f"space toggle · enter {action} · ctrl-c back out",
        "space · enter · ctrl-c back out",
    )


HINT = hints()[0]

TICK = "✓ "
"""`✓` already means *this is fine* elsewhere; here it means *this one is in*. Same
symbol, no new one — and the meaning is carried by the tick's presence rather than
by its colour (docs/CONVENTIONS.md §5, §6)."""

MIXED = "◐ "
"""Some of what this row stands for is in and some is out — a folder only, never a leaf.

The one new symbol this screen needed, and it needed one: a folder has three answers
where a path has two, and the two that already exist both mean *all of them*. `✗` was
never a candidate — it means refused/failed everywhere else in lane, and *out* is
already said by the absence of a mark rather than by a glyph of its own.
"""

BLANK = "  "

SUMMARY_LINES = 1
"""The running count sits between the panel and the footer, always drawn."""

_MARK_STYLES = {TICK: "class:table.good", MIXED: "class:table.warn", BLANK: ""}
"""Colour decorates the mark; the mark is what carries the meaning (§6)."""


def mark_for(node: Node[object], checked: frozenset[object]) -> str:
    """`✓` all in, `◐` a mix, blank all out. A leaf stands for itself, so it has two."""
    leaves = node.leaves
    inside = sum(1 for value in leaves if value in checked)
    if not inside:
        return BLANK
    return TICK if inside == len(leaves) else MIXED


def leaves_of(nodes: Sequence[Node[object]]) -> tuple[object, ...]:
    """Every leaf under a level — what the running count counts, at any depth."""
    return tuple(value for node in nodes for value in node.leaves)


def paint(
    title: str,
    columns: Sequence[Column],
    nodes: Sequence[Node[object]],
    *,
    checked: frozenset[object],
    cursor: int,
    top: int,
    width: int,
    height: int,
    summary: str = "",
    total: int | None = None,
    back: str = "",
) -> Painted:
    """Draw one frame of one level. Pure, which is what makes the layout rules testable.

    `back` is the visible way up, drawn as a row like any other exactly as the lanes
    table draws its own; empty is the root, which has nowhere to go up to. `total` is how
    many leaves the whole tree holds — the count means the same thing on every screen of
    it, so a level cannot be asked to work it out from what it can see.
    """
    rows = [node.row for node in nodes]
    shown_rows = len(rows) + (1 if back else 0)
    cursor = max(0, min(cursor, shown_rows - 1)) if shown_rows else 0
    on_back = bool(back) and cursor == len(rows)

    wanted = () if on_back or not rows else rows[cursor].detail[:MAX_DETAIL_LINES]
    room, detail = vertical(height, wanted, extra=SUMMARY_LINES)
    top = window(shown_rows, cursor, top, room)

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

    for position in range(top, min(top + room, shown_rows)):
        if position == len(rows):
            fragments.append(("class:table.pointer", "❯ " if on_back else "  "))
            fragments.append(("class:table.selected" if on_back else "", f"{BLANK}{back}"))
            fragments.append(("", "\n"))
            continue
        mark = mark_for(nodes[position], checked)
        fragments += row_fragments(
            rows[position],
            kept,
            measured,
            leads,
            short,
            selected=position == cursor,
            mark=(_MARK_STYLES[mark], mark),
        )

    fragments.append(("", "\n"))
    for line in detail:
        fragments.append(("class:table.panel", f"  {clip(line, width - 2)}"))
        fragments.append(("", "\n"))
    if detail:
        fragments.append(("", "\n"))

    counted = tally(len(checked), len(leaves_of(nodes)) if total is None else total)
    if summary:
        counted = f"{counted} · {summary}"
    fragments.append(("class:table.panel", f"  {clip(counted, width - 2)}"))
    fragments.append(("", "\n"))

    shown = ""
    if shown_rows > room:
        shown = f" · {top + 1}–{min(top + room, shown_rows)} of {shown_rows}"
    action = _action(nodes, cursor, on_back=on_back, nested=bool(back))
    fragments.append(
        ("class:table.footer", f"  {clip(footer(width - 2, shown, action), width - 2)}")
    )

    return Painted(fragments=fragments, top=top, room=room)


def _action(nodes: Sequence[Node[object]], cursor: int, *, on_back: bool, nested: bool) -> str:
    """What `Enter` will do to the row under the cursor, for the footer to say."""
    if on_back:
        return UP
    if cursor < len(nodes) and nodes[cursor].children:
        return OPEN
    return UP if nested else ACCEPT


def footer(width: int, shown: str = "", action: str = ACCEPT) -> str:
    """The longest hint that fits, with the scroll position where there is room for it.

    The position goes before any of the hint does: `1–19 of 40` is a convenience, and the
    hint is the only thing on screen saying how to leave.
    """
    available = hints(action)
    for hint in available:
        for whole in (hint + shown, hint):
            if len(whole) <= width:
                return whole
    return available[-1]


def tally(count: int, total: int) -> str:
    """What the screen has decided so far, in one line.

    Worth a line of its own because the rows do not all fit — and because a folder row
    stands for paths that are not on screen at all, so counting rows would mean something
    different on every level of the same tree. `nothing in yet` rather than `0 of 3 in`:
    a count of zero is the one case where the number reads as an error rather than an
    answer.
    """
    if not count:
        return "nothing in yet"
    return f"{count} of {total} in"


class Walk[T]:
    """Where the cursor is standing in the tree, and where it was on the way in.

    One level is one screen, so going into a folder parks the level being left —
    cursor and scroll position both — and coming back out restores it. A screen you
    return to that has forgotten where you were is a screen you have to re-find your
    place in, which is the cost the whole drill-down is supposed to avoid.
    """

    def __init__(self, rows: Callable[[], Sequence[Node[T]]]) -> None:
        self._rows = rows
        self._descent: list[int] = []
        self._parked: list[tuple[int, int]] = []
        self.index = 0
        self.top = 0

    @property
    def nested(self) -> bool:
        """Whether there is a level above this one — which is what draws `← Back`."""
        return bool(self._descent)

    def level(self) -> tuple[tuple[Node[T], ...], str]:
        """This screen's rows and its title — the folder's own row, where there is one.

        The descent is re-walked on every paint because `rows` is the caller's and may
        answer differently (a size landing behind the screen). A descent that no longer
        leads anywhere is truncated to where it still does, the same self-healing the
        lanes table does with a cursor left past the end of a shortened list.
        """
        nodes = tuple(self._rows())
        title = ""
        walked: list[int] = []
        for index in self._descent:
            if index >= len(nodes) or not nodes[index].children:
                break
            title = _title_of(nodes[index])
            nodes = nodes[index].children
            walked.append(index)
        self._descent = walked
        return nodes, title

    def rows_here(self) -> int:
        """Rows on this screen, the visible way back included."""
        nodes, _ = self.level()
        return len(nodes) + (1 if self.nested else 0)

    def node(self) -> Node[T] | None:
        """The node under the cursor, or None on the way-back row."""
        nodes, _ = self.level()
        return nodes[self.index] if self.index < len(nodes) else None

    def enter(self) -> bool:
        """Go into the folder under the cursor, parking this level as it stands."""
        node = self.node()
        if node is None or not node.children:
            return False
        self._parked.append((self.index, self.top))
        self._descent.append(self.index)
        self.index = 0
        self.top = 0
        return True

    def leave(self) -> bool:
        """Back up one level, onto the row that was under the cursor on the way in."""
        if not self._descent:
            return False
        self._descent.pop()
        self.index, self.top = self._parked.pop()
        return True

    def clamp(self) -> None:
        self.index = max(0, min(self.index, max(0, self.rows_here() - 1)))


def _title_of(node: Node[object]) -> str:
    """A level is titled by the row you opened it from — `apps/web/ · 3 ignored paths`.

    §1's rule about a title answering "what am I looking at" rather than repeating the
    screen's own name, got for free: the folder row already says where you are and how
    much is under it.
    """
    first = node.row.cells[0] if node.row.cells else None
    return f"{first.lead}{first.text}" if first is not None else ""


def bindings_for[T](
    walk: Walk[T],
    checked: set[T],
    exit_with: Callable[[frozenset[T] | None], None],
) -> KeyBindings:
    """The keys this checklist answers to: the picker's set, plus `Space`.

    A unit of its own so that "this widget binds exactly one key beyond the picker's"
    is something a test can *check* rather than something the docs assert.
    """
    bindings = KeyBindings()

    def count() -> int:
        return max(1, walk.rows_here())

    @bindings.add("c-c")
    def _abandon(event: KeyPressEvent) -> None:
        del event
        exit_with(None)

    @bindings.add("up")
    def _up(event: KeyPressEvent) -> None:
        del event
        walk.index = (walk.index - 1) % count()

    @bindings.add("down")
    def _down(event: KeyPressEvent) -> None:
        del event
        walk.index = (walk.index + 1) % count()

    @bindings.add("home")
    def _first(event: KeyPressEvent) -> None:
        del event
        walk.index = 0

    @bindings.add("end")
    def _end(event: KeyPressEvent) -> None:
        del event
        walk.index = count() - 1

    @bindings.add("space")
    def _toggle(event: KeyPressEvent) -> None:
        del event
        node = walk.node()
        if node is None:
            return  # the way-back row answers nothing
        leaves = set(node.leaves)
        # The cursor does not move. "The answer changes under the cursor, in place"
        # is the whole requirement, and a list that advances on toggle makes
        # correcting the row you just ticked a two-key job.
        #
        # A folder is all of its leaves at once, and a **mix goes in** rather than out:
        # *in* is the answer somebody reaching for a directory row is after, and the
        # press after it takes the whole subtree out.
        if leaves <= checked:
            checked.difference_update(leaves)
        else:
            checked.update(leaves)

    @bindings.add("enter")
    def _accept(event: KeyPressEvent) -> None:
        del event
        if walk.enter():
            return
        if walk.leave():
            return
        exit_with(frozenset(checked))

    return bindings


def check[T](
    title: str,
    columns: Sequence[Column],
    rows: Callable[[], Sequence[Node[T]]],
    *,
    checked: Iterable[T] = (),
    summary: Callable[[frozenset[T]], str] | None = None,
    fill: Fill | None = None,
    on_render: Callable[[str], None] | None = None,
    input: Input | None = None,
    output: Output | None = None,
) -> frozenset[T]:
    """Every leaf that was in when `Enter` accepted the root. `Ctrl-C` raises `Abandoned`.

    The answers are the widget's own, unlike the table's `rows`: in-or-out is the whole
    of what this screen records, so there is nothing about what an answer *means*
    below the seam to keep out of it. Only **leaves** are ever returned — a folder is a
    row standing for the paths under it, never an answer of its own, which is what keeps
    a partly ignored directory from becoming a step for itself.

    `summary` is the caller's half of the running count — *how much* is coming in,
    which only the action knows, beside the widget's *how many*.
    """
    ticked: set[T] = set(checked)
    walk: Walk[T] = Walk(rows)

    def render() -> FormattedText:
        nodes, here = walk.level()
        walk.clamp()
        size = application.output.get_size()
        settled = frozenset(ticked)
        painted = paint(
            here or title,
            columns,
            nodes,
            checked=settled,
            cursor=walk.index,
            top=walk.top,
            width=size.columns,
            height=size.rows - 1,
            summary=summary(settled) if summary is not None else "",
            total=len(leaves_of(list(rows()))),
            back=BACK_LABEL if walk.nested else "",
        )
        walk.top = painted.top
        if on_render is not None:
            for line in painted.lines:
                on_render(line)
        return FormattedText(painted.fragments)

    bindings = bindings_for(
        walk,
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
