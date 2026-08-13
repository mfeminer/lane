"""Preparing a lane: what a fresh checkout is missing, and what lane does about it.

A lane is a fresh checkout, so **everything `.gitignore` covers is missing from it**.
That is git working correctly, and it is also what makes the checkout unusable: a
dependency tree has to be rebuilt, and an ignored `.env` cannot be rebuilt at all.

Three verbs cover every case found so far, and they are deliberately generic:

* `clone` — a copy-on-write copy from the main clone. Dependency trees, build caches,
  anything the lane may then modify without disturbing the original.
* `link`  — a symlink into the main clone. Large immutable assets; and secrets, where
  always-current beats isolated and one copy beats one per lane.
* `run`   — a configured command, in a configured directory.

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

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path


class Verb(StrEnum):
    """What lane does to one path, or with one command.

    A `StrEnum` because these are also what the configuration file stores and what the
    screen prints, and three spellings of one word is two too many.
    """

    SKIP = "skip"
    CLONE = "clone"
    LINK = "link"
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

    refresh: bool = False
    """`clone` only: reapply on every enter rather than only when it is missing.

    Deliberately not settable from the preparation screen. On the screen where an
    answer is first given the path is absent, so `clone` and a refreshing `clone` do
    exactly the same thing — a screen has no business offering a distinction it cannot
    demonstrate, to someone with no information yet to choose with. Settings, visited
    after living with the answer, is where it is turned on.
    """

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
            case Verb.CLONE:
                return "clone, refreshed" if self.refresh else "clone"
            case _:
                return str(self.verb)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A path git reports as ignored, and everything the screen needs to ask about it.

    `linkable` is git's own judgement, not a guess: `node_modules/` matches directories
    only, so a symlink of that name is an *untracked* file — which would put `● 1
    uncommitted` in the listing and a finding in the close flow, over a link the user
    asked for. So `link` is offered only where git says it would still be ignored.
    """

    path: str
    present: bool
    """Whether the path is already in the lane, which changes what an answer does."""

    linkable: bool = True

    @property
    def label(self) -> str:
        """What the row is called. A path names itself; a `Group` says how many it holds."""
        return self.path

    def cycle(self) -> tuple[Verb, ...]:
        """The verbs `Enter` moves through for this row, in order."""
        if self.linkable:
            return (Verb.SKIP, Verb.CLONE, Verb.LINK)
        return (Verb.SKIP, Verb.CLONE)


GROUP_FROM = 3
"""How many loose ignored files in one directory it takes to become a group row.

A group row costs one keystroke to reach the answers inside it, so it has to save more
than one row to be worth having: two files folded into one row is a wash, three saves
two. This is the first count where grouping pays.
"""

ROOT_LABEL = "./"
"""What a group of loose files at the repository root is called, since `""` shows as
nothing at all."""


@dataclass(frozen=True, slots=True)
class Group:
    """Several loose ignored files under one directory, shown as a single row.

    **Presentation only, and that is a safety property rather than an implementation
    note.** A group is *not* a step for its directory: the directory is only partially
    ignored — that is the entire reason git listed its files separately — so it holds
    tracked work as well, and cloning it would overwrite that. Answering a group applies
    the verb to each path in it and stores one step per path.

    Two consequences worth keeping: a file that appears in that directory later is a path
    nobody has answered, so it is asked about rather than silently swept in; and an answer
    given here means exactly what the same answer means on a row of its own.
    """

    directory: str
    candidates: tuple[Candidate, ...]

    @property
    def label(self) -> str:
        count = len(self.candidates)
        word = "file" if count == 1 else "files"
        shown = f"{self.directory}/" if self.directory else ROOT_LABEL
        return f"{shown} · {count} ignored {word}"

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(candidate.path for candidate in self.candidates)

    def verbs(self) -> tuple[Verb, ...]:
        """What can be answered for the whole group: only what holds for all of it.

        `link` needs every path in the group to be linkable, because one answer covering
        paths it cannot deliver for would be an answer that quietly did something else to
        some of them.
        """
        if all(candidate.linkable for candidate in self.candidates):
            return (Verb.SKIP, Verb.CLONE, Verb.LINK)
        return (Verb.SKIP, Verb.CLONE)

    def summary(self, verbs: Mapping[str, Verb]) -> str:
        """What the row says will happen — one word, even when that word is `mixed`.

        A group can be answered two ways at once, and `mixed` is the honest cell for that:
        short enough never to crowd out the column that answers the screen's question, and
        a plain word rather than a symbol. `breakdown` is what the panel adds to it.
        """
        answers = {verbs[path] for path in self.paths}
        return str(answers.pop()) if len(answers) == 1 else "mixed"

    def breakdown(self, verbs: Mapping[str, Verb]) -> str:
        """`1 clone, 2 skip` — the detail behind `mixed`, for the panel."""
        counted = Counter(verbs[path] for path in self.paths)
        order = (Verb.CLONE, Verb.LINK, Verb.SKIP)
        return ", ".join(f"{counted[verb]} {verb}" for verb in order if counted[verb])


type Item = Candidate | Group
"""One row of the preparation screen: a path to answer, or a folder of them."""


def group(candidates: Sequence[Candidate], threshold: int = GROUP_FROM) -> tuple[Item, ...]:
    """Fold loose ignored files into one row per directory, keeping discovery's order.

    Grouping is by **parent directory and nothing else**: it says nothing about what each
    path is, so a fully ignored directory sitting beside loose files is folded in with
    them like any other path. That is safe precisely because a group is never a step for
    its directory — see `Group`.
    """
    by_directory: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        directory, _, _ = candidate.path.rpartition("/")
        by_directory.setdefault(directory, []).append(candidate)

    # Emitted in the order the candidates arrived, with a group anchored where its **first
    # member** was. Discovery's order is git's, which is sorted; grouping by bucket and
    # then flattening would put `logs/` after `node_modules`, and a list that reads as
    # shuffled is one the eye cannot trust.
    rows: list[Item] = []
    placed: set[str] = set()
    for candidate in candidates:
        directory, _, _ = candidate.path.rpartition("/")
        found = by_directory[directory]
        if len(found) < threshold:
            rows.append(candidate)
            continue
        if directory not in placed:
            placed.add(directory)
            rows.append(Group(directory=directory, candidates=tuple(found)))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class Effect:
    """One thing preparation is about to do to this lane, and how to say it.

    Built for a particular lane, unlike a `Step`: the same stored `clone` is a copy in
    an empty lane and a replacement in one that already has the path.

    **Never holds `Verb.SKIP`.** Both ways of making one — `needed` and `effect_for` —
    answer None for it, because an effect whose verb is "do nothing" is a step looking for
    something to perform.
    """

    step: Step
    overwrites: bool = False

    @property
    def verb(self) -> Verb:
        return self.step.verb

    @property
    def subject(self) -> str:
        return self.step.subject

    def phrase(self) -> str:
        """`Cloning apps/web/node_modules…` — a gerund and an ellipsis, per §10."""
        match self.verb:
            case Verb.CLONE:
                return f"{'Replacing' if self.overwrites else 'Cloning'} {self.subject}…"
            case Verb.LINK:
                return f"Linking {self.subject}…"
            case _:
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
    linkable: frozenset[str] = frozenset(),
    writable: frozenset[str] | None = None,
    problem: str | None = None,
) -> Plan:
    """Work out what to ask and what to do, without touching anything.

    `ignored` is what git found in the **main clone**, where the files actually are.

    The other two are git's answers about the **lane**, where the files would go, and
    they are different questions because a trailing slash is:

    * `writable` — paths the lane's own git ignores in *some* form. A path missing from
      it is one the lane's branch tracks, or does not ignore, so bringing it in would
      dirty the worktree — and it is not offered at all.
    * `linkable` — paths still ignored when named as something other than a directory.
      A path missing from it loses `link` from its cycle, because `node_modules/` matches
      directories only and a symlink is not one.

    `None` means "not asked", which is what the model's own tests want.
    """
    del project  # named for the reader: everything here is about this one project

    candidates = tuple(
        Candidate(
            path=path,
            present=_present(lane_path / path),
            linkable=path in linkable,
        )
        for path in unanswered(steps, ignored)
        if writable is None or path in writable
    )

    effects = tuple(effect for step in steps if (effect := needed(step, lane_path)) is not None)
    return Plan(candidates=candidates, effects=effects, problem=problem)


def effect_for(step: Step, lane_path: Path) -> Effect | None:
    """What a **freshly given** answer does to this lane, or None if it does nothing.

    Different from `needed` in one place, deliberately: a stored `clone` means "put it here
    if it is missing" and leaves an existing path alone, while a *first* answer for a path
    that is already there means "replace it" — which is what the row said in words
    (`clone · overwrites`) before it was given.

    None for `skip`, so an answer of "leave it out" cannot become a step that runs. That is
    a `None` rather than a filter at the call site because the alternative is a `SKIP`
    effect looking for a verb to perform, which is a bug waiting for somewhere to happen.
    """
    if step.verb is Verb.SKIP or not step.usable:
        return None
    return Effect(step=step, overwrites=_present(lane_path / step.subject))


def needed(step: Step, lane_path: Path) -> Effect | None:
    """What this step has to do to this lane, or None when it has nothing to do.

    The common case, and it must be cheap: one `lstat` per step, and no work at all for a
    `skip`. Asked twice — once to build the plan, and again just before a command runs,
    because a guard path a clone was about to satisfy has to be re-examined after it did.
    """
    if not step.usable or step.verb is Verb.SKIP:
        return None

    if step.verb is Verb.RUN:
        if step.unless and _present(lane_path / step.unless):
            return None
        return Effect(step=step)

    present = _present(lane_path / step.path)
    if present and not (step.verb is Verb.CLONE and step.refresh):
        # Already there, and the answer was "put it here", not "keep it current".
        # **Entering a lane never overwrites what the lane changed** unless the user
        # asked for that path to be refreshed.
        return None
    return Effect(step=step, overwrites=present)


def _present(path: Path) -> bool:
    """Whether anything is at `path` — a symlink included, broken or not.

    `exists()` alone follows symlinks, so a link into a main clone that has since lost
    the target would read as absent and be replaced. It is *there*; it is the lane's,
    and lane does not silently take it away.
    """
    return path.is_symlink() or path.exists()


def with_verb(step: Step, verb: Verb) -> Step:
    """The same step, answered differently."""
    return replace(step, verb=verb)
