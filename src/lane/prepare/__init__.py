"""Preparing a lane: what a fresh checkout is missing, and what lane does about it.

A lane is a fresh checkout, so **everything `.gitignore` covers is missing from it**.
That is git working correctly, and it is also what makes the checkout unusable: a
dependency tree has to be rebuilt, and an ignored `.env` cannot be rebuilt at all.

Two verbs cover every case found so far, and they are deliberately generic:

* `clone` — a copy-on-write copy from the main clone. Dependency trees, build caches,
  secrets, anything a fresh checkout is missing.
* `run`   — a configured command, in a configured directory.

**A path is in or out, and nothing else.** `link` was a third answer once — a symlink
into the main clone — and it is gone: the question a row asks is *does this come into the
lane*, which has two answers, and a screen that answers it with a checkbox cannot carry a
third. What it cost is worth naming rather than forgetting: a linked path was always
current and existed once rather than once per lane, which suited a large read-only asset.
What it bought is a screen where a dozen paths take a dozen keystrokes.

**lane learns no package manager.** No `yarn`, no `go`, no `cargo` appears anywhere in
this package or anywhere else in the source. Go keeps its caches globally and needs
almost none of this; Node keeps them per project and needs all of it — an asymmetry
lane cannot learn its way out of, because there is always one more ecosystem. The
mechanism is generic and the project-specific knowledge is configuration.

**lane leaks nothing into the projects it manages.** The answers live in lane's own
configuration directory (`store.py`); no marker, no file and no directory is ever
written into a project, so a project cannot tell lane exists.

**Nothing is recorded per lane.** The only state is the filesystem — is the path there
— which is what makes an interrupted or failed preparation repair itself: entering the
lane again simply runs it again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Verb(StrEnum):
    """What lane does to one path, or with one command.

    A `StrEnum` because these are also what the configuration file stores and what the
    screen prints, and three spellings of one word is two too many.

    A `prepare.toml` written by an older lane may say `verb = "link"`; the store drops a
    verb it does not know, so that path is simply asked about again. The symlink already
    in the lane then reads as *already there*, and a tick leaves it exactly as it is.
    """

    SKIP = "skip"
    CLONE = "clone"
    RUN = "run"


@dataclass(frozen=True, slots=True)
class Step:
    """One remembered decision, and everything its verb needs.

    A path for `clone`, `link` and `skip`; a command and a directory for `run`. One
    record shape rather than two, discriminated by `verb`, because that is what keeps
    the file a flat list and the screens a single table.
    """

    project: str
    verb: Verb

    path: str = ""
    """Relative to the repository root, as git reports it."""

    command: str = ""
    directory: str = ""
    """`run` only: where to run it, relative to the lane. Empty means the lane root."""

    unless: str = ""
    """`run` only: skip the command when this path is already in the lane.

    A command has no natural idempotence marker, and a marker file would be per-lane
    state that can go stale. A guard path needs no new state, is the obvious
    configuration, and composes with a `clone` of the same path — the clone satisfies
    the guard, so the command never runs.
    """

    @property
    def subject(self) -> str:
        """What this step is about, for a row that has to name it in one cell."""
        return self.command if self.verb is Verb.RUN else self.path

    @property
    def key(self) -> tuple[str, str]:
        """What makes two steps the same step: one answer per project per subject."""
        return (self.project, self.subject)

    @property
    def usable(self) -> bool:
        """Whether there is anything here to act on."""
        if self.verb is Verb.RUN:
            return bool(self.command)
        return bool(self.path)

    def describe(self) -> str:
        """The stored answer in words, for the settings list.

        Not the same question the preparation screen answers: that one says what will
        happen to a particular lane, and settings has no lane in hand.
        """
        match self.verb:
            case Verb.RUN:
                where = f" · {self.directory}" if self.directory else ""
                return f"run{where}"
            case _:
                return str(self.verb)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A path git reports as ignored, and everything the screen needs to ask about it."""

    path: str
    present: bool = False
    """Whether the path is already in the lane.

    It does not change what a tick *means* — a ticked path that is already there is left
    alone, always — but it changes what a tick will *do*, which is nothing. The row says
    so, because a tick that is a no-op and a tick that copies a gigabyte have to look
    different.
    """

    project: str = ""
    """Which project's path this is. Empty where there is only one in play; settings
    shows several at once and needs it to find the file and to lead the row."""

    @property
    def label(self) -> str:
        """What the row is called. A path names itself; a `Group` says how many it holds."""
        return self.path


GROUP_FROM = 3
"""How many rows a level has to hold before it is worth a folder row of its own.

A folder row costs one keystroke to reach the rows inside it, so it has to save more than
one row to be worth having: two folded into one is a wash, three saves two. This is the
first count where folding pays — below it, a level is drawn in its parent instead, which
is also what collapses a chain of directories with a single child into one row.
"""

ROOT_LABEL = "./"
"""What a group of loose files at the repository root is called, since `""` shows as
nothing at all."""


@dataclass(frozen=True, slots=True)
class Group:
    """A directory of ignored paths, shown as a single row you can go into.

    **Presentation only, and that is a safety property rather than an implementation
    note.** A group is *not* a step for its directory: the directory is only partially
    ignored — that is the entire reason git listed its paths separately — so it holds
    tracked work as well, and cloning it would overwrite that. Answering a group applies
    the answer to each path beneath it and stores one step per path.

    Two consequences worth keeping: a file that appears in that directory later is a path
    nobody has answered, so it is asked about rather than silently swept in; and an answer
    given here means exactly what the same answer means on a row of its own.

    **`items` are the rows one level down, and they may be groups themselves**; the
    `candidates` are every leaf beneath, however deep. A group stands for all of them —
    which is three states rather than two, all in, all out or a mix, and the mark that
    says so is `◐` (docs/CONVENTIONS.md §5). A folder used to be opened out into its own
    rows when its paths disagreed, because a checkbox could not say "some of these"; the
    mark can, so the shape no longer has to lie or to flatten.
    """

    directory: str
    items: tuple[Item, ...]

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        """Every leaf beneath this row, however deep — what one keystroke answers."""
        found: list[Candidate] = []
        for item in self.items:
            found.extend(item.candidates if isinstance(item, Group) else (item,))
        return tuple(found)

    @property
    def label(self) -> str:
        count = len(self.candidates)
        word = "path" if count == 1 else "paths"
        shown = f"{self.directory}/" if self.directory else ROOT_LABEL
        return f"{shown} · {count} ignored {word}"

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(candidate.path for candidate in self.candidates)

    @property
    def project(self) -> str:
        return self.candidates[0].project if self.candidates else ""

    @property
    def present(self) -> bool:
        """Whether any of them is already in the lane — the row says so for the folder."""
        return any(candidate.present for candidate in self.candidates)


type Item = Candidate | Group
"""One row of the preparation screen: a path to answer, or a folder of them."""


def tree(candidates: Sequence[Candidate], threshold: int = GROUP_FROM) -> tuple[Item, ...]:
    """The top of the tree the discovered paths already are, one level at a time.

    Two hundred ignored paths drawn flat is not a screen, and they are not a flat list
    either: they are a tree, and git already put the separators in. This groups on those
    and nothing else — it says nothing about what each path is, so a fully ignored
    directory sitting beside loose files is a leaf beside them like any other path. That
    is safe precisely because a group is never a step for its directory (see `Group`).

    **A level of fewer than `threshold` rows is drawn in its parent instead of behind a
    keystroke.** A folder row costs one press to reach the rows inside it, so it has to
    save more than one row to be worth having: two folded into one is a wash, three saves
    two. A directory with a single child is the extreme of the same rule — no choice is
    being offered, so `apps/web/frontend/node_modules` stays the one row it always was.

    No second git call and no walk of its own: this is the same
    `ls-files -o -i --exclude-standard --directory` answer, split on `/`.
    """
    return _fold_root(_level(candidates, "", threshold), threshold)


def _level(candidates: Sequence[Candidate], prefix: str, threshold: int) -> tuple[Item, ...]:
    """The rows of one directory: its own paths, and a row per directory under it.

    Emitted in the order the candidates arrived, with a folder anchored where its **first
    member** was. Discovery's order is git's, which is sorted; grouping by bucket and then
    flattening would put `logs/` after `node_modules`, and a list that reads as shuffled
    is one the eye cannot trust.
    """
    under: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        segment, slash, _ = candidate.path[len(prefix) :].partition("/")
        if slash:
            under.setdefault(prefix + segment, []).append(candidate)

    rows: list[Item] = []
    placed: set[str] = set()
    for candidate in candidates:
        segment, slash, _ = candidate.path[len(prefix) :].partition("/")
        if not slash:
            rows.append(candidate)
            continue
        directory = prefix + segment
        if directory in placed:
            continue
        placed.add(directory)
        inside = _level(under[directory], f"{directory}/", threshold)
        if len(inside) < threshold:
            # Not a choice worth a screen: its rows belong on this one.
            rows.extend(inside)
        else:
            rows.append(Group(directory=directory, items=inside))
    return tuple(rows)


def _fold_root(rows: Sequence[Item], threshold: int) -> tuple[Item, ...]:
    """The repository root's own loose files, folded into one row like any directory's.

    The root is the one level with no row of its own on a screen above it, so `./` is the
    only place its loose files can be answered in one keystroke. Every other directory
    already has that row — which is why no other level folds its own paths this way.
    """
    loose = [row for row in rows if isinstance(row, Candidate) and "/" not in row.path]
    if len(loose) < threshold:
        return tuple(rows)

    folded = Group(directory="", items=tuple(loose))
    kept: list[Item] = []
    for row in rows:
        if row is loose[0]:
            kept.append(folded)
        elif row not in loose:
            kept.append(row)
    return tuple(kept)


@dataclass(frozen=True, slots=True)
class Effect:
    """One thing preparation is about to do to this lane, and how to say it.

    Built for a particular lane, unlike a `Step`: a stored `clone` has something to do
    in an empty lane and nothing to do in one that already has the path.

    **Never holds `Verb.SKIP`**, because an effect whose verb is "do nothing" is a step
    looking for something to perform — `needed` answers None for it, and `needed` is the
    only way one is made.
    """

    step: Step

    @property
    def verb(self) -> Verb:
        return self.step.verb

    @property
    def subject(self) -> str:
        return self.step.subject

    def phrase(self) -> str:
        """`Cloning apps/web/node_modules…` — a gerund and an ellipsis, per §10."""
        if self.verb is Verb.CLONE:
            return f"Cloning {self.subject}…"
        return f"Running {self.subject}…"


@dataclass(frozen=True, slots=True)
class Plan:
    """What preparation will ask and what it will do, decided before either happens.

    Empty on both counts is the common case — entering a lane that is already ready —
    and it must cost nothing: no screen, no spinner, no line.
    """

    candidates: tuple[Candidate, ...] = ()
    """Discovered paths with no answer yet. These, and only these, are asked about."""

    effects: tuple[Effect, ...] = ()
    """Already-answered steps that have something to do to this lane."""

    problem: str | None = None
    """Set when the answers file could not be read."""

    @property
    def anything_to_do(self) -> bool:
        return bool(self.candidates or self.effects)


def unanswered(steps: Sequence[Step], ignored: Sequence[str]) -> list[str]:
    """Discovered paths this project has no answer for — the only ones ever asked about.

    Its own function because the action needs the list *before* it can build a plan: the
    question "would a symlink here still be ignored" costs a git call, and asking it for
    paths nobody will be asked about is what would turn an already-prepared lane's one
    git call into two.
    """
    answered = {step.subject for step in steps}
    return [path for path in ignored if path not in answered]


def plan(
    *,
    project: str,
    steps: tuple[Step, ...],
    ignored: list[str],
    lane_path: Path,
    writable: frozenset[str] | None = None,
    problem: str | None = None,
) -> Plan:
    """Work out what to ask and what to do, without touching anything.

    `ignored` is what git found in the **main clone**, where the files actually are.

    `writable` is git's answer about the **lane**, where the files would go: paths the
    lane's own git ignores in *some* form, asked in both spellings because a trailing
    slash is a different question. A path missing from it is one the lane's branch tracks,
    or does not ignore, so bringing it in would dirty the worktree — and it is not offered
    at all. `None` means "not asked", which is what the model's own tests want.
    """
    candidates = tuple(
        Candidate(path=path, present=_present(lane_path / path), project=project)
        for path in unanswered(steps, ignored)
        if writable is None or path in writable
    )

    effects = tuple(effect for step in steps if (effect := needed(step, lane_path)) is not None)
    return Plan(candidates=candidates, effects=effects, problem=problem)


def needed(step: Step, lane_path: Path) -> Effect | None:
    """What this step has to do to this lane, or None when it has nothing to do.

    The common case, and it must be cheap: one `lstat` per step, and no work at all for a
    `skip`. Asked twice — once to build the plan, and again just before a command runs,
    because a guard path a clone was about to satisfy has to be re-examined after it did.

    **One function, and a freshly given answer goes through it too.** There used to be a
    second: a first answer for a path already in the lane meant *replace it*, which the
    row said in words. It does not any more — a tick never overwrites what the lane has,
    whether the answer was given a minute ago or last month. That rule is what made one
    function enough, and one function is what stops the rule being true in one place only.
    """
    if not step.usable or step.verb is Verb.SKIP:
        return None

    if step.verb is Verb.RUN:
        if step.unless and _present(lane_path / step.unless):
            return None
        return Effect(step=step)

    if _present(lane_path / step.path):
        # **Entering a lane never overwrites what the lane changed.** A dependency tree
        # patched by hand is work, and losing it silently is the one thing this feature
        # could do that is worse than not existing.
        return None
    return Effect(step=step)


def _present(path: Path) -> bool:
    """Whether anything is at `path` — a symlink included, broken or not.

    `exists()` alone follows symlinks, so a link into a main clone that has since lost
    the target would read as absent and be replaced. It is *there*; it is the lane's,
    and lane does not silently take it away.
    """
    return path.is_symlink() or path.exists()
