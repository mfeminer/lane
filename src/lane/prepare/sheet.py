"""The rows of the preparation screen, and the answers they carry.

**One screen, reached from two directions.** Entering a lane opens it when some path
has no answer yet; settings opens it to review or change anything. They are not two
screens that resemble each other — resemblance drifts — but one, built here and drawn
by `ui/checklist.py`. What differs between the callers is *data*, and it is exactly
two things:

* settings shows several projects at once, so the project leads the row (the dimmed
  `Cell.lead` the lanes table already uses for the same job);
* entering has a lane in hand, so it can say which paths are already in it.

Neither is a difference in behaviour, and neither is allowed to become one.

**A row is in or out.** Ticked means the path comes into the lane, unticked means it
stays out; both are remembered, and every row starts wherever the stored answer left
it. There is no third state, which is what makes a folder of loose files a single
checkbox — and what makes a folder whose paths *disagree* get opened out into its own
rows instead of being made to lie (see `prepare.group`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Container, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lane.prepare import Candidate, Group, Item, Step, Verb, apply, group
from lane.ui.seam import Cell, Column, Row

MEASURING = Cell("measuring…", tone="dim")
ALREADY_THERE = "already there"

_MAX_WORKERS = 8

_SECRET_NAMES = (".env", ".netrc", "id_rsa", "id_ed25519")
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".keystore")
_SECRET_PREFIXES = (".env.", "secrets", "credentials", "id_rsa", "id_ed25519")


def looks_like_secrets(path: str) -> bool:
    """Names that usually mean "this holds a secret".

    A heuristic, and only ever advisory: it never blocks, never changes an answer, and
    names no tool — so it smuggles in no package-manager knowledge.
    """
    name = path.rsplit("/", 1)[-1].lower()
    return (
        name in _SECRET_NAMES
        or name.endswith(_SECRET_SUFFIXES)
        or name.startswith(_SECRET_PREFIXES)
    )


class Sheet:
    """Rows, ticks and sizes for one preparation screen, whichever door it was opened by."""

    def __init__(
        self,
        candidates: Sequence[Candidate],
        *,
        source: Callable[[Candidate], Path],
        inside: Container[tuple[str, str]] = frozenset(),
        lead: bool = False,
        lane: bool = False,
    ) -> None:
        self.candidates = tuple(candidates)
        self._source = source
        self._lead = lead
        self._lane = lane
        self._inside = inside
        self.sizes: dict[tuple[str, str], int | None] = {}
        self._lock = threading.Lock()
        self.items = self._group()

    # -- what the widget draws -----------------------------------------------
    @property
    def columns(self) -> tuple[Column, ...]:
        """What gives way on a narrow terminal, in order: `in lane` first — the cursor
        panel says the same thing in words, so nothing is lost that cannot be got back —
        then `size`, which nothing repeats and which is what stops a database being
        brought in by accident. The **tick** answers the screen's own question and is a
        gutter rather than a column, so it cannot be dropped at all (§13)."""
        columns = [Column("path"), Column("size", drop=1)]
        if self._lane:
            columns.append(Column("in lane", drop=2))
        return tuple(columns)

    def rows(self) -> list[Row[Item]]:
        with self._lock:
            return [self._row(item) for item in self.items]

    @property
    def checked(self) -> frozenset[Item]:
        """What arrives already answered — every row whose paths are all in."""
        return frozenset(
            item for item in self.items if all(self._is_inside(one) for one in _within(item))
        )

    def _row(self, item: Item) -> Row[Item]:
        cells = [
            Cell(item.label, lead=f"{item.project}/" if self._lead else ""),
            self._size_cell(_within(item)),
        ]
        if self._lane:
            cells.append(Cell(_presence(item), tone="dim"))
        return Row(value=item, cells=tuple(cells), detail=self._detail(item))

    def _size_cell(self, candidates: Sequence[Candidate]) -> Cell:
        """One path's size, or a folder's total. `measuring…` until every part has landed."""
        keys = [_key(one) for one in candidates]
        if any(key not in self.sizes for key in keys):
            return MEASURING
        known = [self.sizes[key] for key in keys]
        total = sum(size for size in known if size is not None) if any(known) else None
        return Cell(apply.size_phrase(total), tone="dim")

    def _detail(self, item: Item) -> tuple[str, ...]:
        lines: list[str] = []
        if isinstance(item, Group):
            lines.append(f"{len(item.candidates)} ignored files, answered together.")
        already = [one for one in _within(item) if one.present]
        if already and self._lane:
            lines.append(_left_alone(len(already), len(_within(item))))
        if any(looks_like_secrets(one.path) for one in _within(item)):
            lines.append("Looks like it holds secrets, and every lane would get its own copy.")
        return tuple(lines)

    # -- the answers ---------------------------------------------------------
    def steps(self, chosen: frozenset[Item]) -> tuple[Step, ...]:
        """Every path's answer, in the order they were offered.

        One step per path even for a folder ticked in one go, which is the property that
        keeps a folder safe: it is never a step for its directory. See `prepare.Group`.
        """
        wanted = {one.path for item in chosen for one in _within(item)}
        return tuple(
            Step(
                project=candidate.project,
                verb=Verb.CLONE if candidate.path in wanted else Verb.SKIP,
                path=candidate.path,
            )
            for candidate in self.candidates
        )

    def summary(self, chosen: frozenset[Item]) -> str:
        """How much is actually about to be copied, beside the widget's how many.

        Paths already in the lane are left out of the total, because a tick on one of
        those does nothing — a number that counted them would be describing work lane is
        not going to do.

        With no lane in hand nothing is copied on accepting, so it says **in each lane**
        rather than *coming in*: the same number, and the truth about when it is spent.
        """
        pending = [one for item in chosen for one in _within(item) if not one.present]
        if not pending:
            return ""
        keys = [_key(one) for one in pending]
        if any(key not in self.sizes for key in keys):
            return "still measuring"
        total = sum(size for key in keys if (size := self.sizes[key]) is not None)
        return f"{apply.size_phrase(total)} {'coming in' if self._lane else 'in each lane'}"

    # -- the slow column -----------------------------------------------------
    def fill(self, notify: object) -> None:
        """Measure each path, behind the screen the user is already reading.

        `du` on a large tree is slow — hundreds of milliseconds to seconds — and the
        sizes are what stop someone bringing in a database by accident, so they have to
        be on the row before the answer is given but must not hold up the first paint.
        """
        assert callable(notify)
        outstanding = [one for one in self.candidates if _key(one) not in self.sizes]
        if not outstanding:
            return

        def one(candidate: Candidate) -> None:
            size = apply.measure(self._source(candidate))
            with self._lock:
                self.sizes[_key(candidate)] = size
            notify()

        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(outstanding))) as pool:
            list(pool.map(one, outstanding))

    # -- internals -----------------------------------------------------------
    def _group(self) -> tuple[Item, ...]:
        """Fold each project's loose files separately: two projects both having a `logs/`
        is one folder each, never one row spanning both."""
        by_project: dict[str, list[Candidate]] = {}
        for candidate in self.candidates:
            by_project.setdefault(candidate.project, []).append(candidate)
        items: list[Item] = []
        for found in by_project.values():
            inside = frozenset(one.path for one in found if self._is_inside(one))
            items.extend(group(found, checked=inside))
        return tuple(items)

    def _is_inside(self, candidate: Candidate) -> bool:
        return _key(candidate) in self._inside


def _within(item: Item) -> tuple[Candidate, ...]:
    """The paths a row stands for — itself, or every file in the folder."""
    return item.candidates if isinstance(item, Group) else (item,)


def _key(candidate: Candidate) -> tuple[str, str]:
    return (candidate.project, candidate.path)


def _presence(item: Item) -> str:
    """What a tick will *do* to this row, which is the one thing it cannot say itself."""
    within = _within(item)
    already = [one for one in within if one.present]
    if not already:
        return ""
    if len(already) == len(within):
        return ALREADY_THERE
    return f"{len(already)} of {len(within)} already there"


def _left_alone(already: int, total: int) -> str:
    if already == total == 1:
        return "Already in this lane — ticking it leaves what is there exactly as it is."
    if already == total:
        return "All of them are already in this lane — ticking leaves them as they are."
    return f"{already} of them are already in this lane — ticking leaves those as they are."


def inside_from(steps: Iterable[Step]) -> frozenset[tuple[str, str]]:
    """Which `(project, path)` pairs a set of remembered steps says are in."""
    return frozenset(
        (step.project, step.path) for step in steps if step.verb is Verb.CLONE and step.path
    )
