"""The corner hint every widget draws, in one place.

Every widget used to build its own footer string. `checklist.py`'s was the developed
one — three tiers, shedding what it could as the terminal narrowed — and the others
were a constant apiece, which is how four screens ended up with four answers to the
same question. This module is that mechanism, generalised: a screen says which keys
it has and this decides what the corner says about them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MOVE = "↑↓ move"
"""The arrows, named once. The first thing given up, because it teaches nothing."""


@dataclass(frozen=True, slots=True)
class Key:
    """One key a screen answers to, and what it does there."""

    key: str
    does: str


def tiers(keys: Sequence[Key]) -> tuple[str, ...]:
    """The hint, and what it becomes on a terminal too narrow for it.

    It gives things up in the order they can be spared: the arrows first, because
    nobody needs telling that arrows move; then what each key *does*, because the keys
    themselves are the part that has to survive.
    """
    if not keys:
        # `text` and `confirm`: nothing to choose between, so no key of their own and
        # nothing to say about one (docs/CONVENTIONS.md §2).
        return ("",)
    spelled = " · ".join(f"{key.key} {key.does}" for key in keys)
    return (f"{MOVE} · {spelled}", spelled, " · ".join(key.key for key in keys))


MARGIN = 2
"""What the corner keeps clear on the right, matching the two columns every screen
indents its own left edge by."""


def hint(keys: Sequence[Key], width: int, *, shown: str = "") -> str:
    """The longest tier that fits `width`, with the scroll position where there is room.

    The position goes before any of the hint does: `1–19 of 40` is a convenience, and
    what the keys do is the part a screen has to keep saying.
    """
    available = tiers(keys)
    for spelled in available:
        for whole in (spelled + shown, spelled):
            if len(whole) <= width:
                return whole
    return available[-1]


def line(keys: Sequence[Key], width: int, *, shown: str = "") -> str:
    """That hint, pushed into the bottom-right corner. Empty stays empty.

    Bottom-right and dim is where a terminal already shows transient key hints —
    `tmux`'s status line, `fzf`'s own — and it is the corner `checklist.py` was already
    closest to. The styling is the widget's (`class:table.footer`), because dim is a
    tone rather than a string. A screen with nothing to say gets no line at all rather
    than a line of padding.
    """
    room = max(0, width - MARGIN)
    spelled = hint(keys, room, shown=shown)
    return spelled.rjust(room) if spelled else ""
