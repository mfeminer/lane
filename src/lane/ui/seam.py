"""The prompt layer, expressed as an interface actions call — never a library they import.

Actions must not know how the asking happens. That is what lets the session run
under pytest with no terminal, and it is the structural rule that erodes first, so
it is worth restating: **no action imports prompt_toolkit or rich.**

Abandonment is an exception rather than a return value. Threading a sentinel
through every call site makes it possible to forget one, and forgetting one is
exactly how a half-finished action would come about. `Abandoned` cannot fall
through to the next statement.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class Abandoned(Exception):
    """The user backed out of a prompt.

    Not an error: the session catches it and returns to the menu. Because every
    question an action asks comes before its first irreversible step, this is
    always a clean no-op.
    """


BACK_LABEL = "← Back"
"""The visible way out of any prompt that offers choices."""


@dataclass(frozen=True, slots=True)
class Choice[T]:
    """One option in a picker: what the user sees, and what the action gets back."""

    label: str
    value: T
    hint: str = ""


type Tone = Literal["", "good", "warn", "bad", "dim"]
"""What a cell *means*. The widget below the seam decides what colour that is."""


@dataclass(frozen=True, slots=True)
class Cell:
    """One column of one row.

    `lead` is a dim prefix that is part of the text but not part of what
    distinguishes this row from the next — a project name repeated down the whole
    column. It is the first thing dropped when the terminal is too narrow, before
    anything that identifies the row is touched.

    `short` is an abbreviated form of `text`, same meaning and tone, fewer
    characters — tried before a column that must never be dropped or truncated
    (`state`, `pr`) would otherwise run off the edge of a narrow terminal. Empty
    means there is no shorter form, and `text` is used as-is.
    """

    text: str
    tone: Tone = ""
    lead: str = ""
    short: str = ""


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    drop: int = 0
    """Higher goes first when the terminal is too narrow. 0 is never dropped."""


@dataclass(frozen=True, slots=True)
class Row[T]:
    """One line of a table, and what the action gets back if it is chosen."""

    value: T
    cells: tuple[Cell, ...]
    detail: tuple[str, ...] = ()
    """Shown under the table while the cursor is on this row, and nowhere else."""


type Fill = Callable[[Callable[[], None]], None]
"""Fill in the cells that are slow to know, calling `notify` as each one lands.

Handed *to* the UI rather than run by the action, and that asymmetry is the point:
the real UI runs it on a thread so the first paint never waits, while a test runs
it straight through so a scripted table has settled before it is read. Without
that, "render what is known and fill the rest in" could only be tested with sleeps.
"""


class Ui(Protocol):
    """Asking and telling. Both are presentation; an action needs both."""

    # -- asking --------------------------------------------------------------
    def choose[T](
        self,
        title: str,
        options: Sequence[Choice[T]],
        *,
        back: str | None = BACK_LABEL,
        on_render: Callable[[str], None] | None = None,
    ) -> T:
        """Pick one option. A lone candidate is auto-selected without prompting.

        A visible `back` entry is appended, and choosing it raises `Abandoned`:
        going back is something the user can *see*, not a key they have to know.
        Pass `back=None` where the option list already contains its own way out —
        the menu has `quit`, the listing has "back to the menu".

        `on_render` receives each option label as it is offered, for tests.
        """
        ...

    def browse[T](
        self,
        title: str,
        columns: Sequence[Column],
        rows: Callable[[], Sequence[Row[T]]],
        *,
        back: str = BACK_LABEL,
        fill: Fill | None = None,
        cursor: int = 0,
        on_render: Callable[[str], None] | None = None,
    ) -> tuple[T, int]:
        """A table with a cursor over it: the row under the cursor, and where it was.

        This is a screen the user stands in rather than a question they are asked,
        which is the whole difference between it and `choose`. Looking and acting
        are the same widget: whatever happens next happens to the row the cursor is
        on.

        `rows` is a callable because the table redraws from it — the action owns the
        data and any locking around it, the widget owns the drawing. The returned
        index goes back into `cursor` on the next call, so an action leaves the
        cursor where the user left it rather than at the top.

        The visible `back` row and Ctrl-C both raise `Abandoned`, as in `choose`.
        """
        ...

    def text(
        self,
        title: str,
        *,
        default: str = "",
        on_render: Callable[[str], None] | None = None,
    ) -> str:
        """Free text. `q` is ordinary input here; Esc abandons.

        `on_render` receives the hint as it is displayed, for tests.
        """
        ...

    def confirm(
        self,
        title: str,
        *,
        default: bool = False,
        on_render: Callable[[str], None] | None = None,
    ) -> bool:
        """Yes or no. Esc abandons.

        `on_render` receives the hint as it is displayed, for tests.
        """
        ...

    # -- telling -------------------------------------------------------------
    def info(self, text: str) -> None: ...
    def ok(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...
    def detail(self, text: str) -> None:
        """Secondary, dimmed. Paths, hints, URLs."""
        ...

    def heading(self, text: str) -> None: ...
    def blank(self) -> None: ...

    def splash(self, version: str) -> None:
        """Lay the road the session runs on, once, at the top.

        The session's own opening, not an action's: action screens still name
        themselves with `heading` (docs/CONVENTIONS.md §1).
        """
        ...

    def farewell(self) -> None:
        """Close the road. The last thing the session says, by either way out."""
        ...

    def progress[T](self, text: str, work: Callable[[], T]) -> T:
        """Run `work` while showing that something is happening."""
        ...
