"""Entering a lane: **make it ready, then launch the editor.**

Not a menu entry: you enter a lane from the listing, with the cursor on it, because
"which lane?" is a question the listing answers better than a bare picker does
(ADR 0002). What is here is the two halves of entering, in one place, so that opening a
lane and going back into one do exactly the same thing.

## Why preparation belongs here rather than to `open`

A lane is a fresh checkout, so everything `.gitignore` covers is missing from it.
Putting the repair in `enter` buys two things a one-time step at creation would not:
`open` ends by entering the lane it made, so there is **one** code path rather than two;
and the lane is brought up to date **every time** the user goes back into it rather than
once, so an interrupted or failed preparation repairs itself. Nothing needs to remember
that a lane was left half-ready, because nothing is recorded per lane — the only state
is the filesystem, and entering again simply looks again.

## Where the questions sit

`enter` asks everything before it writes its first file, so backing out of the screen is
a clean no-op. Reached from `open`, the worktree already exists — and that is not a
breach of *every question comes before the first irreversible step* but a reading of it
worth stating: **abandoning preparation leaves a complete lane that is unprepared**,
which the listing describes, the close flow can act on, and the next enter repairs.

## The interrupt

Not deferred. Every clone is staged beside its target and renamed into place, so no step
can leave a half-populated path — there is nothing whose half-done state lane could not
describe. And deferring a long install would leave Ctrl-C apparently doing nothing for
minutes, which is the exact perception deferral exists to prevent. But this is not
Zone 1's silent back-out either: earlier steps have completed and are real work, so the
interrupt is reported in one line naming the step it struck.

The bash version's `where`, which printed a path so `cd "$(lane where)"` could move the
caller's shell, is deliberately gone: the editor's integrated terminal is already inside
the worktree, so the workflow never needs it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lane import prepare
from lane.context import Context
from lane.git.backend import GitError
from lane.lanes import Lane
from lane.prepare import Candidate, Effect, Step, Verb, apply
from lane.ui.seam import Abandoned, Cell, Column, Row

BACK = "← Back without entering"
CONTINUE = "\x00continue\x00"
"""The row that applies the answers and goes on. A real row rather than the widget's
`back`, which means the opposite — and which stays where it is, because a screen whose
only way out is an unannounced Ctrl-C is the one thing the visible-exit rule forbids."""

REMEMBERED = "Answers are remembered per project — change them in settings · preparation."

COLUMNS = (
    Column("path"),
    # The one column that answers nothing: it informs a decision the other two make.
    Column("size", drop=1),
    Column("verb"),
)

MEASURING = Cell("measuring…", tone="dim")

_MAX_WORKERS = 8

_SECRET_NAMES = (".env", ".netrc", "id_rsa", "id_ed25519")
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".keystore")
_SECRET_PREFIXES = (".env.", "secrets", "credentials", "id_rsa", "id_ed25519")
"""Names that usually mean "this holds a secret". A heuristic, and only ever advisory:
it never blocks, never changes an answer, and names no tool — so it smuggles in no
package-manager knowledge."""


def enter(context: Context, lane: Lane) -> None:
    """Bring the lane up to date, then open the editor in it."""
    _prepare(context, lane)
    _launch(context, lane)


def _launch(context: Context, lane: Lane) -> None:
    launch = context.environment.launch_editor(context.config.editor, lane.path)
    if launch.launched:
        context.ui.ok(launch.detail)
    else:
        context.ui.warn(f"{launch.detail} — open it yourself: {lane.path}")
        context.ui.detail("  Change the editor command in settings.")


# -- preparation -----------------------------------------------------------------


def _prepare(context: Context, lane: Lane) -> None:
    """Ask about anything new, then apply everything that has something to do.

    The common case is a lane that is already ready, and it must cost nothing: one git
    call, one small file read, one `lstat` per step — and no screen, no spinner, no
    line.
    """
    repo = lane.repo_path(context.projects_root)
    remembered = context.prepare_store().load()
    steps = remembered.for_project(lane.project)

    ignored = _discover(context, repo)
    writable, linkable = _what_the_lane_ignores(context, lane, prepare.unanswered(steps, ignored))

    plan = prepare.plan(
        project=lane.project,
        steps=steps,
        ignored=ignored,
        lane_path=lane.path,
        linkable=linkable,
        writable=writable,
        problem=remembered.problem,
    )

    if plan.problem is not None:
        # Answers were forgotten rather than misread; the screen asking again is itself
        # the signal, and this names the file so it can be fixed or deleted.
        context.ui.warn(plan.problem)

    if not plan.anything_to_do:
        return

    context.ui.heading(f"Preparing {lane.slug}")

    effects = plan.effects
    if plan.candidates:
        answered = _ask(context, lane, repo, plan.candidates)
        context.prepare_store().remember(lane.project, [*steps, *answered])
        fresh = (prepare.effect_for(step, lane.path) for step in answered)
        effects = (*effects, *(effect for effect in fresh if effect is not None))
        _warn_about_secrets(context, answered)

    _apply(context, lane, repo, effects)


def _discover(context: Context, repo: Path) -> list[str]:
    """What git ignores in the **main clone**, where the files actually are.

    One process, and **no spinner**. §10's rule is for a step slow enough to notice, and
    this is 15 ms on a twelve-thousand-file repository — while it runs on the way to the
    editor every single time a lane is entered. A spinner that flashes on the hottest
    path in the application is noise, and it would also be the only thing standing
    between a fully-prepared lane and "preparation costs you nothing visible".

    A repository that cannot be read is no reason to refuse to enter a lane, so this
    reports and carries on with nothing to offer.
    """
    try:
        return context.git.ignored_paths(repo)
    except GitError as exc:
        context.ui.warn(f"Could not look for ignored paths in {repo}: {exc}")
        return []


def _what_the_lane_ignores(
    context: Context, lane: Lane, unanswered: list[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """`(writable, linkable)` — git's own answer about the lane, in one call.

    Two questions, and the trailing slash is what separates them: `node_modules/` asks
    about a directory, bare `node_modules` about anything else. A path the lane ignores
    in *neither* form is one its branch tracks or simply does not ignore, so writing
    there would dirty the worktree — and it is not offered at all.

    Only asked when there is something to ask about, which is what keeps an
    already-prepared lane down to a single git call.
    """
    if not unanswered:
        return frozenset(), frozenset()
    spellings = [spelling for path in unanswered for spelling in (path, f"{path}/")]
    try:
        ignored = context.git.ignored_as_given(lane.path, spellings)
    except GitError:
        # Cannot tell, so offer nothing: dirtying the lane is worse than not preparing it.
        return frozenset(), frozenset()
    return (
        frozenset(path for path in unanswered if path in ignored or f"{path}/" in ignored),
        frozenset(path for path in unanswered if path in ignored),
    )


# -- the screen ------------------------------------------------------------------


class _Sheet:
    """The rows, the answers they carry, and the sizes that arrive behind them.

    The answers are the action's, as the rows already are: the widget calls `toggle` and
    repaints from `rows`. Nothing about what an answer *means* lives below the seam.
    """

    def __init__(self, project: str, candidates: Sequence[Candidate], source: Path) -> None:
        self.project = project
        self.candidates = tuple(candidates)
        self.source = source
        # Everything starts at the answer that changes nothing. One Enter records every
        # visible answer, including untouched rows, so the untouched answer has to be
        # the safe one.
        self.verbs = {candidate.path: Verb.SKIP for candidate in self.candidates}
        self.sizes: dict[str, int | None] = {}
        self._lock = threading.Lock()

    @property
    def title(self) -> str:
        count = len(self.candidates)
        word = "path" if count == 1 else "paths"
        return f"{count} {word} lane has not been told about"

    def rows(self) -> list[Row[str]]:
        with self._lock:
            table = [self._row(candidate) for candidate in self.candidates]
        table.append(
            Row(
                value=CONTINUE,
                cells=(Cell("continue"), Cell(""), Cell("")),
                detail=("Applies the answers above, then opens the editor.",),
            )
        )
        return table

    def _row(self, candidate: Candidate) -> Row[str]:
        measured = candidate.path in self.sizes
        return Row(
            value=candidate.path,
            cells=(
                Cell(candidate.path),
                Cell(apply.size_phrase(self.sizes[candidate.path]), tone="dim")
                if measured
                else MEASURING,
                _verb_cell(candidate, self.verbs[candidate.path]),
            ),
            detail=_candidate_detail(candidate),
        )

    def toggle(self, value: str) -> bool:
        """`Enter` on any row but the last, where there is no answer to change."""
        if value == CONTINUE:
            return False
        candidate = next(one for one in self.candidates if one.path == value)
        cycle = candidate.cycle()
        with self._lock:
            here = cycle.index(self.verbs[value])
            self.verbs[value] = cycle[(here + 1) % len(cycle)]
        return True

    def fill(self, notify: object) -> None:
        """Measure each path, behind the screen the user is already reading.

        `du` on a large tree is slow — hundreds of milliseconds to seconds — and the
        sizes are what stop someone cloning a database by accident, so they have to be
        on the row before the answer is given but must not hold up the first paint.
        """
        assert callable(notify)
        if not self.candidates:
            return

        def one(candidate: Candidate) -> None:
            size = apply.measure(self.source / candidate.path)
            with self._lock:
                self.sizes[candidate.path] = size
            notify()

        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(self.candidates))) as pool:
            list(pool.map(one, self.candidates))

    def answers(self) -> tuple[Step, ...]:
        """Every row's answer, in the order they were offered."""
        return tuple(
            Step(project=self.project, verb=self.verbs[candidate.path], path=candidate.path)
            for candidate in self.candidates
        )


def _verb_cell(candidate: Candidate, verb: Verb) -> Cell:
    """What this answer does to *this* lane, now — which is how the row carries the fact
    that changes what the answer means: whether the path is already there.

    The verb is always named, so every keypress visibly changes something; and the
    destructive case names itself in words, which is what keeps the colour from being
    the only thing that says so.
    """
    if verb is Verb.SKIP:
        return Cell("skip", tone="dim")
    if not candidate.present:
        return Cell(str(verb))
    return Cell(f"{verb} · overwrites", tone="warn")


def _candidate_detail(candidate: Candidate) -> tuple[str, ...]:
    lines: list[str] = []
    if not candidate.linkable:
        lines.append("Ignored as a directory only, so 'link' is not offered for this path.")
    if candidate.present:
        lines.append("Already in this lane — answering here replaces what is there.")
    if _looks_like_secrets(candidate.path):
        lines.append("Looks like it holds secrets: 'link' keeps one copy in the main clone.")
    return tuple(lines)


def _ask(
    context: Context, lane: Lane, repo: Path, candidates: tuple[Candidate, ...]
) -> tuple[Step, ...]:
    """One screen, one row per path, one keystroke per change.

    A queue of prompts is the wrong shape: entering a lane is something the user does
    several times a day on the way to their editor, and three questions in sequence to
    get there is a toll. This is a batch decision over a set, so it looks like one.
    """
    ui = context.ui
    sheet = _Sheet(lane.project, candidates, repo)

    ui.detail(f"  {REMEMBERED}")
    ui.blank()

    ui.browse(
        sheet.title,
        COLUMNS,
        sheet.rows,
        back=BACK,
        fill=sheet.fill,
        toggle=sheet.toggle,
    )
    return sheet.answers()


def _warn_about_secrets(context: Context, answered: tuple[Step, ...]) -> None:
    """Copying a `.env` into every lane multiplies the number of places a secret lives.

    Closing the lane removes the worktree, so they go — but a refused or interrupted
    close leaves them. That is not a reason to skip the feature; it is the reason `link`
    is a real option, and this is where that is said.
    """
    for step in answered:
        if step.verb is Verb.CLONE and _looks_like_secrets(step.path):
            context.ui.warn(
                f"{step.path} looks like it holds secrets, and 'clone' puts a copy in every lane."
            )
            context.ui.detail("  'link' keeps one copy in the main clone — change it in settings.")


def _looks_like_secrets(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return (
        name in _SECRET_NAMES
        or name.endswith(_SECRET_SUFFIXES)
        or name.startswith(_SECRET_PREFIXES)
    )


# -- applying --------------------------------------------------------------------


def _apply(context: Context, lane: Lane, repo: Path, effects: tuple[Effect, ...]) -> None:
    """Every step that has something to do, in order, each under its own spinner.

    Paths before commands: a command usually depends on the paths being in place, and a
    guard path a clone is about to satisfy has to see it.
    """
    ordered = [effect for effect in effects if effect.verb is not Verb.RUN]
    ordered += [effect for effect in effects if effect.verb is Verb.RUN]

    for effect in ordered:
        if effect.verb is Verb.RUN and prepare.needed(effect.step, lane.path) is None:
            # A guard path one of the steps above has just satisfied. Asked again here
            # rather than only when the plan was built, which is what makes the ordering
            # mean anything: `clone node_modules` is exactly what
            # `run … unless node_modules` was waiting for.
            continue
        try:
            outcome = context.ui.progress(effect.phrase(), _work(lane, repo, effect))
        except Abandoned:
            # Zone 1's mechanism, but not its silence: earlier steps completed and are
            # real work, so saying nothing would be a lie. Nothing here is half-done —
            # a clone is staged and swapped — so entering again is the whole repair.
            context.ui.warn(f"Interrupted while {effect.phrase().lower().rstrip('…')}")
            context.ui.detail("  Entering the lane again finishes the job.")
            raise
        _report(context, effect, outcome)


def _work(lane: Lane, repo: Path, effect: Effect) -> Callable[[], apply.Outcome]:
    step = effect.step
    match effect.verb:
        case Verb.CLONE:
            return lambda: apply.clone(repo / step.path, lane.path / step.path)
        case Verb.LINK:
            return lambda: apply.link(repo / step.path, lane.path / step.path)
        case _:
            where = lane.path / step.directory if step.directory else lane.path
            return lambda: apply.run(step.command, where)


def _report(context: Context, effect: Effect, outcome: apply.Outcome) -> None:
    """`✓` / `!` / `✗`, and a failure names the fix on an indented line."""
    ui = context.ui
    subject = effect.subject

    if not outcome.ok:
        ui.error(f"Could not {effect.verb} {subject}: {outcome.detail}")
        ui.detail("  The lane still opens; entering it again tries this step once more.")
        return

    if effect.verb is Verb.RUN:
        ui.ok(f"Ran {subject}")
        return

    if effect.verb is Verb.LINK:
        ui.ok(f"Linked {subject}")
        return

    if outcome.copied:
        # The user configured this expecting it to be free. It was not.
        ui.warn(f"Copied {subject} — copy-on-write was not possible, so this used real disk")
        ui.detail("  doctor says whether your projects and lanes folders can share blocks.")
        return
    ui.ok(f"{'Replaced' if effect.overwrites else 'Cloned'} {subject}")
