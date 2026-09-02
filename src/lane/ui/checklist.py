"""A tree of rows, each in, out or not yet answered, changed under the cursor with one key.

The table's layout with a mark in front of every row, and the one screen in lane
whose rows carry their own answer. It sits **below** the `Ui` seam for the same
reason the picker and the table do — a component with its own tests, driven through
`prompt_toolkit`'s pipe input.

## One level of the tree per screen

Two hundred ignored paths drawn flat is not a screen, it is an ordeal, so the rows
are the branching points and a folder is something you go **into**: the same "you
stand in it and act on it" screen the lanes table is, one level at a time, with a
visible `← Back` row exactly as everywhere else.

## Three answers per leaf, five states per folder

A leaf is **in**, **out**, or **not yet answered** — and the third is not a nicety. With
two states, *out* was the absence of an answer, so a row the user had deliberately kept
out and one they simply had not got to were the same thing; accepting a screen therefore
filed a refusal for every row nobody had looked at, and the path was never offered again.
`Answers` (`seam.py`) is the shape that can tell them apart, and `mark_for` is the
partition that draws them: `✓`, `✗`, `○`, and for a folder — which stands for every leaf
beneath it — `?` when a question is still open under there and `◐` when it is fully
answered and its paths disagree (docs/CONVENTIONS.md §5).

## It binds one key the rest of lane does not

| Key | |
|---|---|
| `↑` `↓` `Home` `End` | move |
| `Space` | answer the row under the cursor — a leaf, or every leaf under a folder |
| `Enter` | act on the row under the cursor, whatever that row is |
| `Ctrl-C` | quit lane |

`Space` is the addition, and it was decided deliberately rather than slipped in
(AGENTS.md, *Going back is visible*): this is the universal multi-select convention,
it is what makes a dozen answers a dozen keystrokes, and a screen where `Enter`
answered the row would need a second key to finish — which is the vocabulary this one
is spending its budget on.

**`Enter` does to a row exactly what that row *is***: opens a folder, leaves the level
from `← Back`, accepts from `apply`, abandons from `discard`, and nothing at all on a
leaf, whose answer is `Space`'s job. No fallthrough, so no row's behaviour has to be
worked out from how deep the screen happens to be — which is what the fallthrough this
replaced got wrong twice over (see `_action`, and `tail_rows` for where the accept went).

## The rows below the tree

`← Back` where there is a level above, then `apply` and `discard`, on **every** level.
Accepting and abandoning are rows for the same reason going back always has been: a
screen whose way forward is a keystroke you have to know is the same fault as one whose
way back is. The root has no `← Back` — it is the level with nothing above it — and it
has the other two like every level does.

## Why not prompt_toolkit's `CheckboxList`

It draws every option into one window with no scrolling of its own — the defect
AGENTS.md already measured on `picker.pick`, where 300 branches became 304 lines
with the cursor walking off the bottom of the terminal. It also has no columns, no
dim lead, no cursor panel, and no way to let a slow column land behind the first
paint. All four are things this screen needs, and all four the table already has.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import Output

from lane.ui.footer import Key
from lane.ui.footer import line as footer_line
from lane.ui.picker import ESCAPE_TIMEOUT
from lane.ui.seam import (
    BACK_LABEL,
    FINISH,
    Abandoned,
    Answers,
    Column,
    Fill,
    Finish,
    Node,
    Quit,
)
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

APPLY, DISCARD = FINISH.accept, FINISH.reject
"""The two rows every level ends with, and what `Enter` on each of them does.

Rows rather than keys, exactly as `← Back` is: the vocabulary is closed (AGENTS.md,
*Going back is visible*), and a screen whose way forward is a keystroke you have to know
is the same fault as one whose way back is. Lower case, one word, a verb — §4, the same
rule the menu's own entries follow.

They are on **every** level, root and nested alike. Reachable only from the root is what
the accept used to be, and on a tree whose every path sits under a folder that meant a
screen with no way to finish at all.
"""

NOTHING, OPEN, UP = "", "open", "go up"
"""What `Enter` does to the row under the cursor, in the footer's words.

`NOTHING` is a leaf, and it is not an oversight: a leaf's answer is `Space`'s job, so
`Enter` there has nothing left to do. What it used to do instead was decided by how deep
the screen happened to be — accept at the root, go up anywhere else — which is how a
press on a **file** ended up leaving the level it was pressed in. The footer stops naming
`enter` where `enter` does nothing, rather than naming a key that teaches a lie.
"""


def tail_rows(nested: bool, finish: Finish = FINISH) -> tuple[str, ...]:
    """The rows below the tree, in the order they are drawn.

    `← Back` first where there is a level to go back to, because it belongs with the
    tree it is leaving; then the two that end every level. One function so that "apply
    and discard are reachable at every depth" is a single fact rather than one repeated
    in `paint`, in `Walk` and in the key bindings.
    """
    return ((BACK_LABEL,) if nested else ()) + (finish.accept, finish.reject)


BACK_DETAIL = "Goes up one level. Every answer given so far is kept."
"""What `← Back` does, for the panel under the cursor.

The widget's own words, because the row is the widget's: it moves the cursor a level
and nothing else, whatever the screen is a screen of. The other two say something the
caller decides (`Finish`), and the tree's rows get theirs from `Row.detail`.
"""


def tail_detail(label: str, finish: Finish = FINISH) -> str:
    """What the row under the cursor will do, in the panel's words.

    Looked up by label, which says what the row **is** because `Finish` refuses to be
    built out of two that read alike. Two of the three are the caller's — the reject row
    is the one that has to have a panel line, being the only one on screen that throws
    work away, and a row whose label is a single verb cannot say by itself how much that
    verb covers.
    """
    if label == BACK_LABEL:
        return BACK_DETAIL
    return finish.accept_detail if label == finish.accept else finish.reject_detail


def keys_for(action: str = NOTHING) -> tuple[Key, ...]:
    """The keys this screen has, for the one renderer that draws every corner.

    It names `space` because `space` is the key this screen adds, and names what
    `enter` will do to the row under the cursor because that differs per row — on a
    **leaf** `enter` does nothing, so it is not named at all, because naming a key that
    does nothing teaches a lie. The table's corner names neither, because the table adds
    no key and `Enter` there always means one thing.

    `ctrl-c back out` is **not** in it, and used to be. It was there because Ctrl-C meant
    something lane-specific on this screen — *back out* — and a hint clipped to `ctr…`
    would not have made that visible. Neither half of that reasoning survives: the way
    out is the `discard` row, which is visible in the way §2 actually asks for, and
    Ctrl-C now means the one thing every terminal user already assumes it means
    (AGENTS.md, *Ctrl-C quits lane*).
    """
    answering = (Key("space", "answer"),)
    if not action:
        return answering
    return (*answering, Key("enter", action))


TICK = "✓ "
"""Every leaf this row stands for is **in**.

`✓` already means *this is fine* elsewhere; here it means *this one is in*. Same
symbol, no new one — and the meaning is carried by the tick's presence rather than
by its colour (docs/CONVENTIONS.md §5, §6)."""

CROSS = "✗ "
"""Every leaf this row stands for is **explicitly out**, and none is unanswered.

A widened use of `✗` rather than a fourth glyph, exactly the move `TICK` already made:
`✗` means refused/failed elsewhere in lane, and *out* is the same family of meaning —
this row was refused. What separates it from *unanswered* is which mark is present, not
what colour it is drawn in (§5, §6). *Out* used to be the absence of a mark, which is
precisely what could not be told apart from a question nobody had answered.
"""

UNSET = "○ "
"""**Nothing** this row stands for has been answered — an empty ring for an empty answer.

The state the old two-state screen could not draw, because it had no glyph left: *out*
was the absence of a mark, so a row nobody had touched and a row deliberately left out
looked identical. Every row starts here.
"""

PARTLY = "? "
"""**Something** under this row is still unanswered — a folder only, never a leaf.

Deliberately not another circle. `○`/`◐`/`✗`/`✓` all answer *how much of this is in*, and
this one answers a different question — *is there still a question in here* — so a shape
from that family would be read as a fifth fill level and mistaken for `◐`. `?` cannot be:
it is the one mark on the screen that is not a circle at all, which is what §5 asks for
when two states mean different things and must not be told apart by colour alone.
"""

MIXED = "◐ "
"""Every leaf beneath is answered, and they disagree — a folder only, never a leaf.

A folder has more answers than a path, and the marks that say *all in* and *all out* both
mean *all of them*, so a mix forced into either is a row that lies about paths not on
screen. Distinct from `?`: this folder has no question left in it, it has a real mix of
answers (docs/CONVENTIONS.md §5).
"""

BLANK = "  "
"""No mark: the gutter of a row that carries no answer — `← Back`, `apply`, `discard`."""

SUMMARY_LINES = 1
"""The running count sits between the panel and the footer, always drawn."""

_MARK_STYLES = {
    TICK: "class:table.good",
    CROSS: "class:table.bad",
    UNSET: "class:table.warn",
    PARTLY: "class:table.warn",
    MIXED: "class:table.warn",
    BLANK: "",
}
"""Colour decorates the mark; the mark is what carries the meaning (§6)."""


def mark_for[T](node: Node[T], answers: Answers[T]) -> str:
    """Which of the five states a row is in, from the counts of what is beneath it.

    The partition over a folder's `in`/`out`/`unset` leaves. Its five cases are mutually
    exclusive and exhaustive, which is a property worth having in one place: a folder
    stands for paths that are not on screen, so a state with no mark of its own would be
    drawn as one of the others and lie about them.

    | | |
    |---|---|
    | `unset == total` | nothing here is answered — `○` |
    | `0 < unset < total` | something here is still unanswered — `?` |
    | `unset == 0 and in == total` | all in — `✓` |
    | `unset == 0 and out == total` | all out — `✗` |
    | `unset == 0 and 0 < in < total` | decided, and they disagree — `◐` |

    A **leaf** is the degenerate case of the same partition rather than a rule of its
    own: it stands for one value, so `total` is 1 and only the first three rows can ever
    apply — which is exactly its three answers. That is why there is one function here
    and not two, and why `◐` and `?` cannot appear on a path.
    """
    leaves = node.leaves
    inside = sum(1 for value in leaves if answers.get(value) is True)
    outside = sum(1 for value in leaves if answers.get(value) is False)
    unanswered = len(leaves) - inside - outside

    if unanswered == len(leaves):
        return UNSET
    if unanswered:
        return PARTLY
    if inside == len(leaves):
        return TICK
    if outside == len(leaves):
        return CROSS
    return MIXED


def leaves_of(nodes: Sequence[Node[object]]) -> tuple[object, ...]:
    """Every leaf under a level — what the running count counts, at any depth."""
    return tuple(value for node in nodes for value in node.leaves)


def paint[T](
    title: str,
    columns: Sequence[Column],
    nodes: Sequence[Node[T]],
    *,
    answers: Answers[T],
    cursor: int,
    top: int,
    width: int,
    height: int,
    summary: str = "",
    total: int | None = None,
    nested: bool = False,
    finish: Finish = FINISH,
) -> Painted:
    """Draw one frame of one level. Pure, which is what makes the layout rules testable.

    `nested` says whether this level has one above it, which is the only thing that
    differs between the root's trailing rows and a folder's: `apply` and `discard` are
    drawn on both, `← Back` only where there is somewhere to go back to. `total` is how
    many leaves the whole tree holds — the count means the same thing on every screen of
    it, so a level cannot be asked to work it out from what it can see.
    """
    rows = [node.row for node in nodes]
    tail = tail_rows(nested, finish)
    shown_rows = len(rows) + len(tail)
    cursor = max(0, min(cursor, shown_rows - 1)) if shown_rows else 0
    on_tail = cursor >= len(rows)

    wanted: tuple[str, ...] = ()
    if on_tail:
        wanted = (tail_detail(tail[cursor - len(rows)], finish),)
    elif rows:
        wanted = rows[cursor].detail[:MAX_DETAIL_LINES]
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
        if position >= len(rows):
            here = position == cursor
            fragments.append(("class:table.pointer", "❯ " if here else "  "))
            label = tail[position - len(rows)]
            fragments.append(("class:table.selected" if here else "", f"{BLANK}{label}"))
            fragments.append(("", "\n"))
            continue
        mark = mark_for(nodes[position], answers)
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

    inside = sum(1 for answer in answers.values() if answer)
    counted = tally(inside, len(leaves_of(nodes)) if total is None else total)
    if summary:
        counted = f"{counted} · {summary}"
    fragments.append(("class:table.panel", f"  {clip(counted, width - 2)}"))
    fragments.append(("", "\n"))

    shown = ""
    if shown_rows > room:
        shown = f" · {top + 1}–{min(top + room, shown_rows)} of {shown_rows}"
    action = _action(nodes, cursor, tail=tail)
    fragments.append(("class:table.footer", footer_line(keys_for(action), width, shown=shown)))

    return Painted(fragments=fragments, top=top, room=room)


def _action[T](nodes: Sequence[Node[T]], cursor: int, *, tail: Sequence[str]) -> str:
    """What `Enter` will do to the row under the cursor, for the footer to say.

    One rule, and it is the whole of §1's table: what `Enter` does depends on nothing
    except what the row under the cursor **is**. No fallthrough, so there is no row whose
    behaviour has to be worked out from how deep the screen happens to be.
    """
    if cursor >= len(nodes):
        label = tail[cursor - len(nodes)]
        return UP if label == BACK_LABEL else label
    return OPEN if nodes[cursor].children else NOTHING


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

    def __init__(self, rows: Callable[[], Sequence[Node[T]]], finish: Finish = FINISH) -> None:
        self._rows = rows
        self.finish = finish
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
        """Rows on this screen, the trailing ones included."""
        nodes, _ = self.level()
        return len(nodes) + len(tail_rows(self.nested, self.finish))

    def tail_row(self) -> str:
        """Which of the trailing rows the cursor is on, or `""` when it is on the tree."""
        nodes, _ = self.level()
        tail = tail_rows(self.nested, self.finish)
        position = self.index - len(nodes)
        return tail[position] if 0 <= position < len(tail) else ""

    def node(self) -> Node[T] | None:
        """The node under the cursor, or None on one of the trailing rows."""
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
    answered: dict[T, bool],
    exit_with: Callable[[Answers[T] | None], None],
) -> KeyBindings:
    """The keys this checklist answers to: the picker's set, plus `Space`.

    A unit of its own so that "this widget binds exactly one key beyond the picker's"
    is something a test can *check* rather than something the docs assert.
    """
    bindings = KeyBindings()

    def count() -> int:
        return max(1, walk.rows_here())

    @bindings.add("c-c")
    def _quit(event: KeyPressEvent) -> None:
        # Not this screen's way back — `discard` is that, and `← Back` the way up a
        # level. Ctrl-C leaves lane, from any depth, as it does at every other prompt.
        event.app.exit(exception=Quit)

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
            return  # `← Back`, `apply` and `discard` answer nothing
        # The cursor does not move. "The answer changes under the cursor, in place"
        # is the whole requirement, and a list that advances on toggle makes
        # correcting the row you just ticked a two-key job.
        leaves = node.leaves
        if not node.children:
            # A leaf: the first press *answers* it, and every press after it changes
            # the answer. Unset is where a row starts, never somewhere Space can put
            # it back — a screen that could un-answer a row would make "I have
            # decided about this one" impossible to state.
            answered[leaves[0]] = not answered.get(leaves[0], False)
            return
        # A folder is all of its leaves at once, and everything short of *all in* goes
        # **in**: *in* is the answer somebody reaching for a directory row is after, and
        # the press after it takes the whole subtree out. An unanswered leaf counts
        # towards "not all in", so one press on a folder nobody has touched brings it in.
        inside = all(answered.get(value) is True for value in leaves)
        for value in leaves:
            answered[value] = not inside

    @bindings.add("enter")
    def _chosen(event: KeyPressEvent) -> None:
        del event
        # What `Enter` does is decided by what the row **is**, and by nothing else. The
        # "otherwise leave, otherwise accept" fallthrough this replaced is what sent
        # `Enter` on a *file* up a level, and what left the accept reachable only from a
        # root-level leaf — which a tree whose paths all sit under folders does not have.
        if walk.node() is not None:
            walk.enter()  # a folder opens; on a leaf there is nothing to open
            return
        match walk.tail_row():
            case label if label == BACK_LABEL:
                walk.leave()
            case label if label == walk.finish.accept:
                exit_with(dict(answered))
            case _:
                exit_with(None)

    return bindings


def check[T](
    title: str,
    columns: Sequence[Column],
    rows: Callable[[], Sequence[Node[T]]],
    *,
    answers: Answers[T] | None = None,
    summary: Callable[[Answers[T]], str] | None = None,
    fill: Fill | None = None,
    finish: Finish = FINISH,
    on_render: Callable[[str], None] | None = None,
    input: Input | None = None,
    output: Output | None = None,
) -> Answers[T]:
    """Every leaf that was answered when the accept row was chosen; the reject row raises
    `Abandoned`. Which two rows those are is `finish`'s to say — `apply` and `discard`
    where the caller does not name them, `close` and `leave open` on the close screen.

    The answers are the widget's own, unlike the table's `rows`: in-or-out is the whole
    of what this screen records, so there is nothing about what an answer *means*
    below the seam to keep out of it. Only **leaves** are ever returned — a folder is a
    row standing for the paths under it, never an answer of its own, which is what keeps
    a partly ignored directory from becoming a step for itself.

    `summary` is the caller's half of the running count — *how much* is coming in,
    which only the action knows, beside the widget's *how many*.
    """
    ticked: dict[T, bool] = dict(answers or {})
    walk: Walk[T] = Walk(rows, finish)

    def render() -> FormattedText:
        nodes, here = walk.level()
        walk.clamp()
        size = application.output.get_size()
        settled = dict(ticked)
        painted = paint(
            here or title,
            columns,
            nodes,
            answers=settled,
            cursor=walk.index,
            top=walk.top,
            width=size.columns,
            height=size.rows - 1,
            summary=summary(settled) if summary is not None else "",
            total=len(leaves_of(list(rows()))),
            nested=walk.nested,
            finish=finish,
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
