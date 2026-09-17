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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class Abandoned(Exception):
    """The user backed out of a prompt.

    Not an error: the session catches it and returns to the menu. Because every
    question an action asks comes before its first irreversible step, this is
    always a clean no-op.
    """


class Quit(Exception):
    """The user pressed Ctrl-C. Leave lane.

    A different thing from `Abandoned`, and the difference is the whole point: backing
    out is a **visible row** — `← Back`, `discard`, the menu's `quit`-adjacent entries —
    and it returns to the screen above. Ctrl-C is not a way back at all any more, so it
    cannot share an exception with one. The session ends by the same door `quit` uses,
    farewell included.

    Not `KeyboardInterrupt`: that one means the interrupt landed while lane was *working*,
    where a step may be half-done and the session says so. At a prompt nothing is under
    way, so saying it would be a lie. Two situations, two exceptions, one outcome.
    """


BACK_LABEL = "← Back"
"""The visible way out of any prompt that offers choices."""


@dataclass(frozen=True, slots=True)
class Finish:
    """The two rows a `check` level ends with: the way on, and the way out.

    Rows rather than keys, exactly as `BACK_LABEL` is — that part is the widget's and
    is not negotiable. The **words** are the caller's, because what accepting a screen
    does is: a checklist of ignored paths applies answers, and the close screen closes a
    lane. `apply`/`discard` said in one vocabulary what the other one cannot mean.

    The two details are the caller's for the same reason. A row whose label is a single
    verb cannot say by itself how much that verb covers, which is why the panel line
    exists at all, and the answer differs per screen just as the verb does.
    """

    accept: str = "apply"
    reject: str = "discard"
    accept_detail: str = (
        "Records every answer given so far. Anything still unanswered is asked again."
    )
    reject_detail: str = "Records nothing at all — every answer on this screen is thrown away."

    def __post_init__(self) -> None:
        """Three rows end a level, and the widget tells them apart by what they say.

        So two that read alike are not a cosmetic problem: whichever is matched first
        answers for both, and the other becomes a row the user can put the cursor on and
        press `Enter` on to no effect — a screen with no way to accept it, or none to
        leave it. A blank label is the same screen by a different route. Refused here,
        where a `Finish` is built once at import, rather than found on a screen someone
        is standing in.
        """
        labels = (self.accept, self.reject, BACK_LABEL)
        if not all(labels):
            raise ValueError("a row that ends a level needs a word on it")
        if len(set(labels)) != len(labels):
            raise ValueError(
                f"the rows that end a level must read differently: "
                f"{self.accept!r}, {self.reject!r} and {BACK_LABEL!r}"
            )


FINISH = Finish()
"""What a screen that says nothing else ends with — the checklist's own two words."""


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


@dataclass(frozen=True, slots=True)
class Node[T]:
    """One row of a checklist, and whatever it stands for.

    A **leaf** has no children: it is one thing, with one answer of its own, and its
    `value` is what comes back when the screen is accepted. A node **with** children is
    a folder: a row you can go into, standing for every leaf beneath it however deep —
    which is five states rather than a leaf's three, because it can also be *partly*
    unanswered (`Answers`, and `checklist.mark_for`).

    The tree is the caller's; one level of it is a screen. Nothing about what the
    answers *mean* lives here, exactly as with `Row`.
    """

    row: Row[T]
    children: tuple[Node[T], ...] = ()

    @property
    def leaves(self) -> tuple[T, ...]:
        """Every value beneath this row — what one keystroke on it answers."""
        if not self.children:
            return (self.row.value,)
        return tuple(value for child in self.children for value in child.leaves)


type Fill = Callable[[Callable[[], None]], None]
"""Fill in the cells that are slow to know, calling `notify` as each one lands.

Handed *to* the UI rather than run by the action, and that asymmetry is the point:
the real UI runs it on a thread so the first paint never waits, while a test runs
it straight through so a scripted table has settled before it is read. Without
that, "render what is known and fill the rest in" could only be tested with sleeps.
"""


type Answers[T] = Mapping[T, bool]
"""Every leaf that has been **answered**, and which way — in (`True`) or out (`False`).

A key that is **absent** is the third answer: *nobody has said*. Two states could not
hold it — a set knows "in it" or "not in it", so *explicitly out* and *never asked*
collapsed into one thing, and a screen accepted with rows nobody had looked at recorded
a decision for every one of them. Three states are what let `apply` mean "commit what I
have decided" rather than "answer everything I did not touch".
"""


type Summary[T] = Callable[[Answers[T]], str]
"""What the caller can add to a checklist's running count that the widget cannot know.

The widget counts *how many* are in, because it owns the ticks. *How much* — the total
size of what is about to be brought into the lane — is the action's, because the sizes
are. Both end up on one line so the answer to "what have I just decided" is never off
the top of a scrolling screen.
"""


class Ui(Protocol):
    """Asking and telling. Both are presentation; an action needs both.

    **Every asking method takes a `key`, and the real implementations ignore it.** It
    names the question — not the title, which is prose §8 expects to be reworded —
    so that a flag on the command line can answer it before it is ever drawn
    (`cli.answers.Prefilled`). A prompt with no key can only ever be asked.
    """

    # -- asking --------------------------------------------------------------
    def choose[T](
        self,
        title: str,
        options: Sequence[Choice[T]],
        *,
        back: str | None = BACK_LABEL,
        on_render: Callable[[str], None] | None = None,
        key: str = "",
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
        key: str = "",
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

    def check[T](
        self,
        title: str,
        columns: Sequence[Column],
        rows: Callable[[], Sequence[Node[T]]],
        *,
        answers: Answers[T] | None = None,
        summary: Summary[T] | None = None,
        fill: Fill | None = None,
        finish: Finish = FINISH,
        on_render: Callable[[str], None] | None = None,
        key: str = "",
    ) -> Answers[T]:
        """Every leaf that was answered, and which way, when `apply` was chosen.

        The third screen shape, and the one for a decision taken over a *set*: `choose`
        asks one question, `browse` is a screen you stand in and act on one row of, and
        this is a screen you stand in where every row carries its own answer and one
        keystroke changes it.

        `rows` is a **tree**, one level of it per screen, because two hundred ignored
        paths drawn flat is not a screen. A `Node` with no children is a leaf; one with
        children is a folder standing for every leaf beneath it, and only leaves are ever
        returned. `Space` answers the row under the cursor, a folder and all of it at
        once. `Enter` does to a row exactly what that row *is*: it opens a folder, leaves
        a level from `← Back`, accepts from `apply`, abandons from `discard`, and on a
        leaf it does nothing at all — the leaf's answer is `Space`'s job.

        **Three answers per leaf, not two**: in, out, and *not yet answered*, which is
        where every row starts (`Answers`). A leaf left unanswered is absent from the
        result, so a caller records nothing for it and can ask again — which is what
        makes `apply` mean "commit what I have decided" on a screen that still has
        unanswered rows on it.

        `answers` is what arrives already answered, so config can open the same screen
        over decisions made months ago and show them as they stand — including the paths
        it has no answer for, which two states could not tell from the ones it refused.

        `apply` and `discard` are rows on **every** level, root and nested alike, so
        neither is reachable only by walking back to the top; `← Back` is drawn above
        them wherever there is a level to go back to, and moves the cursor without
        discarding anything. `discard` raises `Abandoned`. `Ctrl-C` quits lane, as
        everywhere else.

        `finish` is what those two rows are **called**, and what their panel lines say.
        The shape is the widget's and never varies; the words belong to the screen,
        because a decision taken over a set of paths and one taken over what closing a
        lane does are accepted for different reasons (`Finish`).
        """
        ...

    def text(
        self,
        title: str,
        *,
        default: str = "",
        key: str = "",
    ) -> str:
        """Free text. `q` is ordinary input here; `Ctrl-C` quits lane."""
        ...

    def confirm(
        self,
        title: str,
        *,
        default: bool = False,
        key: str = "",
    ) -> bool:
        """Yes or no. `Ctrl-C` quits lane."""
        ...

    # -- telling -------------------------------------------------------------
    def info(self, text: str) -> None: ...
    def ok(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...
    def detail(self, text: str) -> None:
        """Secondary, dimmed. Paths, hints, URLs."""
        ...

    def table(
        self,
        title: str,
        columns: Sequence[Column],
        rows: Sequence[Row[object]],
    ) -> None:
        """A table **printed**, for a caller that cannot stand in one.

        Telling, not asking — which is the whole difference from `browse`. `lane list`
        in a pipe has no cursor to move and nowhere to go back to, so it gets the rows
        and the same column rules and nothing else. The layout is shared with `browse`
        rather than written twice (docs/CONVENTIONS.md §13).
        """
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
