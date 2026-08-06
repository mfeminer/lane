"""The real `Ui`: prompt_toolkit for asking, rich for telling.

Together with `picker.py` and `render.py`, this is the **only** place either
library is imported. An action that reaches for `prompt_toolkit` stops being
testable without a terminal, which is why AGENTS.md names that as one of the two
structural rules that erode first.

Key handling differs deliberately between prompt types:

* a prompt that offers choices — `q` abandons (see `picker.py`)
* a prompt that takes free text — `q` is ordinary input, so **Esc** abandons

Both accept Esc everywhere, and Ctrl-C behaves like Esc inside a prompt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from prompt_toolkit.input import Input
from prompt_toolkit.output import Output
from rich.console import Console

from lane.ui import render
from lane.ui.picker import confirm as confirm_widget
from lane.ui.picker import pick, prompt_text
from lane.ui.seam import BACK_LABEL, Abandoned, Choice, Column, Fill, Row
from lane.ui.table import browse as browse_table

_BACK = object()


class ConsoleUi:
    """Asks and tells, on a real terminal."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console if console is not None else render.make_console()

    # -- asking --------------------------------------------------------------
    def choose[T](
        self,
        title: str,
        options: Sequence[Choice[T]],
        *,
        back: str | None = BACK_LABEL,
        on_render: Callable[[str], None] | None = None,
        input: Input | None = None,
        output: Output | None = None,
    ) -> T:
        """Append the visible way back, then hand off to the picker widget.

        Doing it here rather than in every action means no action can forget it, and
        the label stays in one place.
        """
        offered: list[Choice[T | object]] = [Choice(o.label, o.value, o.hint) for o in options]
        if back is not None and len(options) > 1:
            # Not for a lone candidate: that is auto-selected, and adding an entry
            # would turn a question with one answer into a question with two.
            offered.append(Choice(back, _BACK))

        if on_render is not None:
            for option in offered:
                on_render(option.label)

        chosen = pick(title, offered, input=input, output=output)
        if chosen is _BACK:
            raise Abandoned
        return chosen  # type: ignore[return-value]

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
        input: Input | None = None,
        output: Output | None = None,
    ) -> tuple[T, int]:
        """Hand off to the table widget, with the visible way back supplied here.

        Same reason as `choose`: doing it at this layer means no action can forget
        it, and the label stays in one place.
        """
        return browse_table(
            title,
            columns,
            rows,
            back,
            fill=fill,
            cursor=cursor,
            on_render=on_render,
            input=input,
            output=output,
        )

    def text(
        self,
        title: str,
        *,
        default: str = "",
        on_render: Callable[[str], None] | None = None,
        input: Input | None = None,
        output: Output | None = None,
    ) -> str:
        if on_render is not None:
            on_render("ctrl-c back out")
        return prompt_text(title, default=default, input=input, output=output)

    def confirm(
        self,
        title: str,
        *,
        default: bool = False,
        on_render: Callable[[str], None] | None = None,
        input: Input | None = None,
        output: Output | None = None,
    ) -> bool:
        if on_render is not None:
            on_render("ctrl-c back out")
        return confirm_widget(title, default=default, input=input, output=output)

    # -- telling -------------------------------------------------------------
    # `render.clip_long_words`: a path has no spaces, so under rich's default
    # wrapping it's one long "word" that folds mid-character across lines once it
    # doesn't fit. Clipping only words that are themselves too long (never `text`
    # as a whole, and never with `no_wrap`) makes a path degrade the way the lanes
    # table already does — a clean single-line ellipsis — while leaving ordinary
    # prose (doctor's remedies, a close summary's findings) wrapping at its spaces exactly as
    # before.
    def _clipped(self, text: str) -> str:
        return render.escape(render.clip_long_words(text, self._console.width))

    def info(self, text: str) -> None:
        self._console.print(self._clipped(text))

    def ok(self, text: str) -> None:
        self._console.print(f"[green]✓[/green] {self._clipped(text)}")

    def warn(self, text: str) -> None:
        self._console.print(f"[yellow]![/yellow] {self._clipped(text)}")

    def error(self, text: str) -> None:
        self._console.print(f"[red]✗[/red] {self._clipped(text)}")

    def detail(self, text: str) -> None:
        self._console.print(f"[dim]{self._clipped(text)}[/dim]")

    def heading(self, text: str) -> None:
        self._console.print(f"\n[bold]{self._clipped(text)}[/bold]")

    def blank(self) -> None:
        self._console.print()

    def progress[T](self, text: str, work: Callable[[], T]) -> T:
        """Long steps — fetching origin, asking GitHub — must show something."""
        with self._console.status(f"[dim]{render.escape(text)}[/dim]", spinner="dots"):
            return work()
