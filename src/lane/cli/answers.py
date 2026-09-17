"""Answers supplied on the command line, standing where the prompt layer stands.

This is the whole of how a subcommand reaches the same code an interactive session
reaches. `lane open --project acme` does not reimplement what `open_lane._gather`
decides; it **answers** the question `_gather` was going to ask, in advance. The
action is unchanged and cannot tell the difference, which is the only arrangement
in which the two entry points cannot drift apart.

Three outcomes for any one prompt, and they are the whole contract:

* the flag was given — the prompt is not drawn, anywhere, terminal or not;
* it was not, and a terminal is there — the real `Ui` asks it, same wording, same
  validation, same re-ask loop;
* it was not, and there is no terminal — `NeedsAnswer`, naming the question and the
  flag that would have answered it. **Never a wait for input nothing can give.**

A prompt is found by its `key`, not by its title: titles are prose, and
`docs/CONVENTIONS.md` §8 expects them to be reworded. A reword must not silently
re-route a flag.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from lane.ui.seam import (
    BACK_LABEL,
    FINISH,
    Answers,
    Cell,
    Choice,
    Column,
    Fill,
    Finish,
    Node,
    Row,
    Summary,
    Ui,
)

_MISSING = object()
_DEFAULT = object()

type Decision[T] = Callable[[Sequence[Node[T]], Answers[T]], Answers[T]]
"""What a `check` is answered with: the rows it would have drawn, in, and the answers out."""


class NeedsAnswer(Exception):
    """A question with nothing to answer it and no terminal to ask it in."""

    def __init__(
        self,
        key: str,
        question: str,
        *,
        flag: str = "",
        remedy: str = "",
        offered: Sequence[str] = (),
        spent: bool = False,
    ) -> None:
        super().__init__(
            f"{question}: the value given was not accepted"
            if spent
            else f"{question}: no answer was given and there is no terminal to ask in"
        )
        self.key = key
        self.question = question
        self.flag = flag
        self.remedy = remedy
        """What to do about it, where no flag can answer the question.

        Preparation is the one that needs this: which ignored paths come into a lane is
        a screen, not a value, so the way out is to answer it once — in a terminal, or
        in settings · preparation — rather than to pass something here."""

        self.offered = tuple(offered)
        self.spent = spent
        """The flag was given, used, and the prompt came round again — so its value was
        refused by the validation behind that prompt. A different fact from never having
        had one, and the difference is what the user needs to read."""


class NoSuchOption(Exception):
    """A flag named something the screen does not offer.

    Never the same thing as a missing answer, and never quietly turned into a
    prompt: the user said which project, branch or lane they meant, and asking them
    again would be answering a different question from the one they asked.
    """

    def __init__(
        self,
        key: str,
        question: str,
        given: object,
        *,
        flag: str = "",
        offered: Sequence[str] = (),
    ) -> None:
        named = ", ".join(offered[:_NAMED]) if offered else ""
        rest = f", and {len(offered) - _NAMED} more" if len(offered) > _NAMED else ""
        super().__init__(
            f"{question}: nothing here is '{given}'"
            + (f" — there is {named}{rest}" if named else "")
        )
        self.key = key
        self.question = question
        self.given = given
        self.flag = flag
        self.offered = tuple(offered)


_NAMED = 8
"""How many of what was offered a refusal names. Three hundred branches is a real
screen, and a refusal that prints all of them is one nobody reads."""


class Prefilled:
    """A `Ui` whose answers may already be known, falling back to a real one."""

    DEFAULT = _DEFAULT
    """Answer with whatever the prompt itself would have defaulted to.

    A flag that "defaults to the first listed option" must not write that option down
    a second time — the list belongs to the screen, and a team that configures its own
    branch prefixes changes it. So the command line says *the default*, and the prompt
    says what that is.
    """

    def __init__(
        self,
        script: dict[str, object],
        ui: Ui,
        *,
        interactive: bool,
        flags: dict[str, str] | None = None,
        remedies: dict[str, str] | None = None,
    ) -> None:
        self._script = dict(script)
        self._ui = ui
        """The real one. **Telling always reaches it** — a refusal, a spinner and a
        `✓` are not input, so they happen whether or not anything can be asked. Only
        *asking* is gated, and `interactive` is that gate."""

        self._interactive = interactive
        self._flags = dict(flags or {})
        self._remedies = dict(remedies or {})
        self._spent: set[str] = set()
        """Keys already used. A prompt that comes round again is one whose validation
        refused the answer — a branch name git will not take, a lane name already open
        — and replaying the same value into it would loop for ever."""

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
        answer = self._answer(key)
        if answer is _MISSING:
            return self._ask(
                key, title, lambda ui: ui.choose(title, options, back=back, on_render=on_render)
            )
        if answer is _DEFAULT:
            # Where the cursor starts, which is what pressing Enter would have taken.
            return options[0].value
        for option in options:
            if answer is option.value or answer == option.value or answer == option.label:
                return option.value
        raise NoSuchOption(
            key,
            title,
            answer,
            flag=self._flags.get(key, ""),
            offered=[option.label for option in options],
        )

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
        """A row is named by what is written on it, exactly as a test script names one.

        The slow column is **not** filled when the answer is already known: nothing is
        going to be looked at, and the fill is `gh` on the listing. It is handed over
        untouched when the real screen opens.
        """
        answer = self._answer(key)
        if answer is _MISSING:
            return self._ask(
                key,
                title,
                lambda ui: ui.browse(
                    title,
                    columns,
                    rows,
                    back=back,
                    fill=fill,
                    cursor=cursor,
                    on_render=on_render,
                ),
            )
        offered = rows()
        if answer is _DEFAULT:
            return offered[0].value, 0
        for index, row in enumerate(offered):
            if _names(row, answer):
                return row.value, index
        raise NoSuchOption(
            key,
            title,
            answer,
            flag=self._flags.get(key, ""),
            offered=[row.cells[0].text for row in offered if row.cells],
        )

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
        """The one prompt whose answer cannot be written down in advance.

        Its rows are facts about this lane — which branches it abandoned, which paths
        it has never been told about — so a flag can only be checked against them once
        they exist. The scripted answer is therefore a **decision taken against the
        rows**: it is handed what the screen would have drawn and what was already
        answered, and returns the answers. That is where `--delete-others` finds out
        it named a branch this lane never used.
        """
        answer = self._answer(key)
        if answer is _MISSING:
            return self._ask(
                key,
                title,
                lambda ui: ui.check(
                    title,
                    columns,
                    rows,
                    answers=answers,
                    summary=summary,
                    fill=fill,
                    finish=finish,
                    on_render=on_render,
                ),
            )
        decide = cast(Decision[T], answer)
        return decide(list(rows()), dict(answers or {}))

    def text(
        self,
        title: str,
        *,
        default: str = "",
        key: str = "",
    ) -> str:
        answer = self._answer(key)
        if answer is _MISSING:
            return self._ask(key, title, lambda ui: ui.text(title, default=default))
        if answer is _DEFAULT:
            return default
        return str(answer)

    def confirm(
        self,
        title: str,
        *,
        default: bool = False,
        key: str = "",
    ) -> bool:
        answer = self._answer(key)
        if answer is _MISSING:
            return self._ask(key, title, lambda ui: ui.confirm(title, default=default))
        return bool(answer)

    # -- the three outcomes --------------------------------------------------
    def _answer(self, key: str) -> object:
        if not key:
            return _MISSING
        answer = self._script.pop(key, _MISSING)
        if answer is not _MISSING:
            self._spent.add(key)
        return answer

    def _ask[T](self, key: str, question: str, real: Callable[[Ui], T]) -> T:
        if not self._interactive:
            raise NeedsAnswer(
                key,
                question,
                flag=self._flags.get(key, ""),
                remedy=self._remedies.get(key, ""),
                spent=key in self._spent,
            )
        answer: T = real(self._ui)
        return answer

    # -- telling ---------------------------------------------------------------
    # Straight through, every one of them. Nothing here is input, so none of it is
    # gated: a subcommand in a pipe still says what it did, on stderr, while stdout
    # carries the JSON and nothing else.
    def info(self, text: str) -> None:
        self._ui.info(text)

    def ok(self, text: str) -> None:
        self._ui.ok(text)

    def warn(self, text: str) -> None:
        self._ui.warn(text)

    def error(self, text: str) -> None:
        self._ui.error(text)

    def detail(self, text: str) -> None:
        self._ui.detail(text)

    def heading(self, text: str) -> None:
        self._ui.heading(text)

    def table(
        self,
        title: str,
        columns: Sequence[Column],
        rows: Sequence[Row[object]],
    ) -> None:
        self._ui.table(title, columns, rows)

    def blank(self) -> None:
        self._ui.blank()

    def splash(self, version: str) -> None:
        self._ui.splash(version)

    def farewell(self) -> None:
        self._ui.farewell()

    def progress[T](self, text: str, work: Callable[[], T]) -> T:
        return self._ui.progress(text, work)


def _names(row: Row[object], answer: object) -> bool:
    """Whether a supplied answer means this row: its value, or any of its cells."""
    if answer is row.value or answer == row.value:
        return True
    return any(_says(cell, answer) for cell in row.cells)


def _says(cell: Cell, answer: object) -> bool:
    return answer == cell.text or answer == f"{cell.lead}{cell.text}"
