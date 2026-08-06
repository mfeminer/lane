"""The three fakes, and only these three.

`GitBackend` is never faked — tests use the real one against temporary
repositories. The filesystem runs for real too.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lane.environment import EditorLaunch
from lane.github.client import PrLookup, not_applicable
from lane.ui.seam import BACK_LABEL, Abandoned, Choice, Column, Fill, Row


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
    """Fully controls the pull request answer, including "I cannot tell you".

    The close path decides from this answer alone and never probes the
    environment separately — which is what makes this one stub sufficient.
    """

    def __init__(self, answer: PrLookup | None = None) -> None:
        self._answer = answer
        self.asked: list[tuple[str | None, str | None]] = []

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
        on_render: Callable[[str], None] | None = None,
    ) -> tuple[T, int]:
        """Records the whole table, then answers it from the script.

        `fill` is run straight through with a no-op `notify`, so a scripted table
        has settled by the time it is read. The real UI runs it on a thread; that
        difference is the only reason "render what is known, fill the rest in" can
        be asserted without sleeps.
        """
        if fill is not None:
            fill(lambda: None)

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

        answer = self._next(title)
        if isinstance(answer, str) and answer.lower() in {"back", back.lower()}:
            raise Abandoned
        # An integer answers by position, so a test can say "the second lane".
        if isinstance(answer, int) and not isinstance(answer, bool):
            if not 0 <= answer < len(table):
                raise AssertionError(f"FakeUi row {answer} is out of range for {title!r}")
            return table[answer].value, answer
        for index, row in enumerate(table):
            if answer is row.value or answer == row.value:
                return row.value, index
            if any(
                answer == cell.text or answer == f"{cell.lead}{cell.text}" for cell in row.cells
            ):
                return row.value, index
        raise AssertionError(
            f"FakeUi answer {answer!r} matches no row of {title!r}: "
            f"{[row.cells[0].text for row in table]}"
        )

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


@dataclass
class Recorder:
    """Collects calls, for asserting that something did or did not happen."""

    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def record(self, name: str, *args: object) -> None:
        self.calls.append((name, args))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]
