"""Type to narrow a list, on every list-shaped prompt lane has.

One implementation, used by `choose`, `browse` and `check` alike — for the reason
AGENTS.md already gives for the picker, the table and the checklist sharing as much
as they do: three screens that merely resemble each other drift, and these three are
the same screen with different rows in it.

## It needs no new key, and that is the test it had to pass

Nothing printable is bound in any of the three today: `y`/`n` exist only in `confirm`
and `Space` only in `check`. So a letter cannot collide with anything already there,
which is the same argument `Space` had to make before it was allowed to exist
(AGENTS.md, *Going back is visible*).

`Space` itself is **not** a filter character anywhere, including the two screens where
it is unbound. It already means *answer this row* on one of the three, and a key that
means one thing on one list screen and another on the next is exactly what the closed
vocabulary exists to prevent. A filter is one word here, which is what a filter over
paths, lane names and branch names is anyway.

`Backspace` takes the last character back. There is no key to clear the whole filter:
backspacing to empty is the text editing every terminal user already has, and
`Ui.text` already relies on it (docs/CONVENTIONS.md §3).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from lane.ui.footer import Key
from lane.ui.seam import Row

KEY = Key("type", "to filter")
"""What every filtering screen adds to its corner — one more clause in the same tiered
line the rest of the hint already is, never a second line (docs/CONVENTIONS.md §3a)."""


def matching(texts: Sequence[str], text: str) -> list[int]:
    """Which entries the filter keeps, by position.

    Case-insensitive substring: a lane is remembered by a word in the middle of it as
    often as by how it starts, and nobody types a filter with the shift key.
    """
    if not text:
        return list(range(len(texts)))
    wanted = text.casefold()
    return [index for index, each in enumerate(texts) if wanted in each.casefold()]


def row_text(row: Row[object]) -> str:
    """What a table or checklist row is matched against: the text it draws.

    The cells the widget already assembles, leads included, because a lead is on screen.
    `Row` and `Cell` gain no second "searchable text" field — what the user can see is
    what they can filter on, and a field beside the cells is one more thing that can
    fall out of step with them.
    """
    return " ".join(f"{cell.lead}{cell.text}" for cell in row.cells)


def status(*, matched: int, total: int, text: str) -> str:
    """The line a filtering screen draws immediately under its title.

    A filter is never a mode the user has to remember they are in: what they typed is
    on screen, with what it left of the list beside it. Nothing typed, nothing said.
    """
    if not text:
        return ""
    if not matched:
        # docs/CONVENTIONS.md §12: an empty list is a line, not a frame with nothing in
        # it. The line names the filter, because backspacing is what undoes it.
        return f"No matches for '{text}'."
    return f"{matched} of {total} · filter: {text}"


@dataclass(slots=True)
class Filter:
    """What has been typed on this screen so far. One buffer per screen."""

    text: str = ""


def follow(chosen: int | None, kept: Sequence[int]) -> int:
    """Where the cursor goes when the filter changes.

    It stays on the row it was on where that row still matches, and lands on the first
    match otherwise — so narrowing a list under a cursor never quietly moves the answer
    out from under `Enter`.
    """
    if chosen is not None and chosen in kept:
        return kept.index(chosen)
    return 0


def bind(
    bindings: KeyBindings,
    current: Filter,
    *,
    chosen: Callable[[], int | None],
    moved: Callable[[int | None], None],
) -> None:
    """Bind typing and `Backspace` on a list-shaped prompt.

    `Keys.Any` is a catch-all that every exact binding still outranks, which is what
    keeps `Enter`, the arrows, `Ctrl-C` and the checklist's `Space` meaning exactly what
    they meant before.

    `chosen` reports which row the cursor is on, in the caller's own numbering, before
    the text moves; `moved` is handed it afterwards, so the widget can put the cursor
    back on that row where it survived (`follow`).
    """

    def change(text: str) -> None:
        was = chosen()
        current.text = text
        moved(was)

    @bindings.add(Keys.Any)
    def _typed(event: KeyPressEvent) -> None:
        if len(event.data) != 1 or not event.data.isprintable() or event.data == " ":
            # Control characters, whole escape sequences, and `Space` — which already
            # answers a row on the checklist and so types nothing on any of them.
            return
        change(current.text + event.data)

    @bindings.add("backspace")
    def _rubbed_out(event: KeyPressEvent) -> None:
        del event
        if current.text:
            change(current.text[:-1])
