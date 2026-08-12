"""The three fakes, and only these three.

`GitBackend` is never faked — tests use the real one against temporary
repositories. The filesystem runs for real too.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lane.environment import EditorLaunch
from lane.github.client import DependentLookup, Dependents, PrLookup, not_applicable
from lane.ui.seam import BACK_LABEL, Abandoned, Choice, Column, Fill, Row, Toggle


class FakeEnvironment:
    """A machine you describe rather than one you have."""

    def __init__(
        self,
        *,
        interactive: bool = True,
        tools: dict[str, str] | None = None,
        app_dirs: Sequence[Path] = (),
        editor_launches: bool = True,
    ) -> None:
        self._interactive = interactive
        # tool name -> resolved path. Absent means not on PATH.
        self._tools = tools if tools is not None else {"git": "/usr/bin/git", "gh": "/usr/bin/gh"}
        self._app_dirs = {Path(p) for p in app_dirs}
        self._editor_launches = editor_launches
        self.launched: list[tuple[str, Path]] = []

    def is_interactive(self) -> bool:
        return self._interactive

    def which(self, tool: str) -> str | None:
        if not tool:
            return None
        return self._tools.get(tool)

    def tool_version(self, tool: str, *args: str) -> str | None:
        if tool not in self._tools:
            return None
        return f"{tool} version 1.2.3 (fake)"

    def launch_editor(self, command: str, path: Path) -> EditorLaunch:
        """Records the intent. The suite must never actually open an editor."""
        if self._editor_launches and command in self._tools:
            self.launched.append((command, path))
            return EditorLaunch(launched=True, detail=f"Launching {command} in the lane.")
        return EditorLaunch(launched=False, detail=f"'{command}' is not on your PATH")

    def directory_exists(self, path: Path) -> bool:
        return path in self._app_dirs


class StubGitHubClient:
    """Fully controls both pull request answers, including "I cannot tell you".

    The close path decides from these answers alone and never probes the
    environment separately — which is what makes this one stub sufficient.

    `dependents` defaults to "nothing is based on this branch", so every test written
    before stacked pull requests existed still describes the situation it meant to.
    """

    def __init__(
        self, answer: PrLookup | None = None, dependents: DependentLookup | None = None
    ) -> None:
        self._answer = answer
        self._dependents = dependents if dependents is not None else Dependents(())
        self.asked: list[tuple[str | None, str | None]] = []
        self.asked_about_dependents: list[str | None] = []

    def set(self, answer: PrLookup) -> None:
        self._answer = answer

    def pull_request_for(
        self, *, branch: str | None, remote_url: str | None, cwd: Path
    ) -> PrLookup:
        del cwd
        self.asked.append((branch, remote_url))
        if self._answer is None:
            return not_applicable("not-github")
        return self._answer

    def pull_requests_based_on(
        self, *, branch: str | None, remote_url: str | None, cwd: Path
    ) -> DependentLookup:
        del cwd, remote_url
        self.asked_about_dependents.append(branch)
        return self._dependents


@dataclass
class Told:
    """One thing lane said to the user, so tests can assert on it."""

    kind: str
    text: str


class FakeUi:
    """Replays scripted answers and records what the user was told.

    Answers are consumed in order. The sentinel `ABANDON` raises `Abandoned`,
    which is how a test drives "the user pressed Esc".
    """

    ABANDON = object()

    def __init__(self, answers: Sequence[object] = ()) -> None:
        self._answers = list(answers)
        self.told: list[Told] = []
        self.asked: list[str] = []

    # -- the script ----------------------------------------------------------
    def push(self, *answers: object) -> None:
        self._answers.extend(answers)

    def _next(self, question: str) -> object:
        self.asked.append(question)
        if not self._answers:
            raise AssertionError(f"FakeUi ran out of answers at: {question!r}")
        answer = self._answers.pop(0)
        if answer is FakeUi.ABANDON:
            raise Abandoned
        return answer

    # -- asking --------------------------------------------------------------
    def choose[T](
        self,
        title: str,
        options: Sequence[Choice[T]],
        *,
        back: str | None = BACK_LABEL,
        on_render: Callable[[str], None] | None = None,
    ) -> T:
        if on_render is not None:
            for option in options:
                on_render(option.label)
        answer = self._next(title)
        # "back" answers the visible Back entry the real Ui appends.
        if (
            back is not None
            and isinstance(answer, str)
            and answer.lower() in {"back", back.lower()}
        ):
            raise Abandoned
        # A test may answer with the value itself or with a visible label.
        for option in options:
            if answer is option.value or answer == option.value or answer == option.label:
                return option.value
        raise AssertionError(
            f"FakeUi answer {answer!r} matches no option of {title!r}: {[o.label for o in options]}"
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
        toggle: Toggle[T] | None = None,
        on_render: Callable[[str], None] | None = None,
    ) -> tuple[T, int]:
        """Records the whole table, then answers it from the script.

        `fill` is run straight through with a no-op `notify`, so a scripted table
        has settled by the time it is read. The real UI runs it on a thread; that
        difference is the only reason "render what is known, fill the rest in" can
        be asserted without sleeps.

        An answer of the form `("space", <row>)` presses Space on that row, so a test
        drives *"change the first row, change the third, continue"* as a script:

            FakeUi([("space", "apps/web/node_modules"), ("space", 2), "continue"])
        """
        if fill is not None:
            fill(lambda: None)

        def paint() -> list[Row[T]]:
            """Record the table the way the real widget draws it — once per repaint."""
            table = list(rows())
            self.told.append(Told("table", title))
            for row in table:
                self.told.append(
                    Told("row", " | ".join(f"{cell.lead}{cell.text}" for cell in row.cells))
                )
                for line in row.detail:
                    self.told.append(Told("panel", line))
            if on_render is not None:
                for row in table:
                    on_render(" ".join(f"{cell.lead}{cell.text}" for cell in row.cells))
                on_render(back)
            return table

        table = paint()
        while True:
            answer = self._next(title)
            if isinstance(answer, str) and answer.lower() in {"back", back.lower()}:
                raise Abandoned
            if _is_space(answer):
                if toggle is None:
                    raise AssertionError(f"FakeUi pressed space on {title!r}, which has no toggle")
                assert isinstance(answer, tuple)
                index = _index_of(title, table, answer[1])
                toggle(table[index].value)
                # The answer belongs to the action, so the table is read again exactly as
                # a repaint would: what changed is on screen, and recorded.
                table = paint()
                continue
            index = _index_of(title, table, answer)
            return table[index].value, index

    def text(
        self,
        title: str,
        *,
        default: str = "",
        on_render: Callable[[str], None] | None = None,
    ) -> str:
        if on_render is not None:
            on_render("ctrl-c back out")
        answer = self._next(title)
        if answer == "":
            return default
        assert isinstance(answer, str), f"text() needs a str, got {answer!r}"
        return answer

    def confirm(
        self,
        title: str,
        *,
        default: bool = False,
        on_render: Callable[[str], None] | None = None,
    ) -> bool:
        if on_render is not None:
            on_render("ctrl-c back out")
        answer = self._next(title)
        assert isinstance(answer, bool), f"confirm() needs a bool, got {answer!r}"
        return answer

    # -- telling -------------------------------------------------------------
    def info(self, text: str) -> None:
        self.told.append(Told("info", text))

    def ok(self, text: str) -> None:
        self.told.append(Told("ok", text))

    def warn(self, text: str) -> None:
        self.told.append(Told("warn", text))

    def error(self, text: str) -> None:
        self.told.append(Told("error", text))

    def detail(self, text: str) -> None:
        self.told.append(Told("detail", text))

    def heading(self, text: str) -> None:
        self.told.append(Told("heading", text))

    def blank(self) -> None:
        self.told.append(Told("blank", ""))

    def splash(self, version: str) -> None:
        # The drawing is `splash.py`'s business and pinned in the snapshots; what a
        # session test cares about is that the road was laid, and which version it named.
        self.told.append(Told("splash", f"lane {version}"))

    def farewell(self) -> None:
        self.told.append(Told("farewell", ""))

    def progress[T](self, text: str, work: Callable[[], T]) -> T:
        """Runs the work straight through; the spinner is a real-UI concern."""
        self.told.append(Told("progress", text))
        return work()

    # -- assertions helpers --------------------------------------------------
    @property
    def transcript(self) -> str:
        return "\n".join(t.text for t in self.told)

    def said(self, needle: str) -> bool:
        return needle.lower() in self.transcript.lower()

    def unanswered(self) -> int:
        return len(self._answers)


def _is_space(answer: object) -> bool:
    return isinstance(answer, tuple) and len(answer) == 2 and answer[0] == "space"


def _index_of(title: str, table: Sequence[Row[object]], answer: object) -> int:
    """Which row a scripted answer means: its position, its value, or any cell text."""
    if isinstance(answer, int) and not isinstance(answer, bool):
        if not 0 <= answer < len(table):
            raise AssertionError(f"FakeUi row {answer} is out of range for {title!r}")
        return answer
    for index, row in enumerate(table):
        if answer is row.value or answer == row.value:
            return index
        if any(answer == cell.text or answer == f"{cell.lead}{cell.text}" for cell in row.cells):
            return index
    raise AssertionError(
        f"FakeUi answer {answer!r} matches no row of {title!r}: "
        f"{[row.cells[0].text for row in table]}"
    )


@dataclass
class Recorder:
    """Collects calls, for asserting that something did or did not happen."""

    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def record(self, name: str, *args: object) -> None:
        self.calls.append((name, args))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]
