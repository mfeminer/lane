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

from collections.abc import Callable, Sequence
from pathlib import Path

from lane import prepare
from lane.context import Context
from lane.git.backend import GitError
from lane.lanes import Lane
from lane.prepare import Candidate, Effect, Step, Verb, apply
from lane.prepare.sheet import Sheet, looks_like_secrets
from lane.ui.seam import Abandoned

REMEMBERED = "Answers are remembered per project — change them in settings · preparation."


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
    writable = _what_the_lane_ignores(context, lane, prepare.unanswered(steps, ignored))

    plan = prepare.plan(
        project=lane.project,
        steps=steps,
        ignored=ignored,
        lane_path=lane.path,
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
        answered = _ask(context, repo, plan.candidates)
        context.prepare_store().remember(lane.project, [*steps, *answered])
        fresh = (prepare.needed(step, lane.path) for step in answered)
        effects = (*effects, *(effect for effect in fresh if effect is not None))

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


def _what_the_lane_ignores(context: Context, lane: Lane, unanswered: list[str]) -> frozenset[str]:
    """Which of these the lane's own git ignores — git's own answer, in one call.

    Asked in **both spellings**, and the trailing slash is the whole reason: `node_modules/`
    matches directories only, bare `node_modules` anything else. A path the lane ignores in
    *neither* form is one its branch tracks or simply does not ignore, so bringing it in
    would dirty the worktree — and it is not offered at all. That is what stops lane ever
    writing over a tracked file.

    Only asked when there is something to ask about, which is what keeps an
    already-prepared lane down to a single git call.
    """
    if not unanswered:
        return frozenset()
    spellings = [spelling for path in unanswered for spelling in (path, f"{path}/")]
    try:
        ignored = context.git.ignored_as_given(lane.path, spellings)
    except GitError:
        # Cannot tell, so offer nothing: dirtying the lane is worse than not preparing it.
        return frozenset()
    return frozenset(path for path in unanswered if path in ignored or f"{path}/" in ignored)


# -- the screen ------------------------------------------------------------------


def _ask(context: Context, repo: Path, candidates: tuple[Candidate, ...]) -> tuple[Step, ...]:
    """One screen, one row per path or per folder, one keystroke per answer.

    A queue of prompts is the wrong shape, and so is a row you have to go *into*: entering
    a lane is something the user does several times a day on the way to their editor. This
    is a batch decision over a set, so it looks like one — `Space` on each row that should
    come in, `Enter` to get on with it.

    The same `Sheet` settings opens, with a lane in hand rather than without one.
    """
    ui = context.ui
    sheet = Sheet(candidates, source=lambda one: repo / one.path, lane=True)

    ui.detail(f"  {REMEMBERED}")
    ui.blank()

    chosen = ui.check(
        _title(candidates),
        sheet.columns,
        sheet.rows,
        checked=sheet.checked,
        summary=sheet.summary,
        fill=sheet.fill,
    )
    answered = sheet.steps(chosen)
    _warn_about_secrets(context, answered)
    return answered


def _title(candidates: Sequence[Candidate]) -> str:
    """Counts *paths*, not rows: a folder row says for itself how many it holds."""
    count = len(candidates)
    word = "path" if count == 1 else "paths"
    return f"{count} {word} lane has not been told about"


def _warn_about_secrets(context: Context, answered: tuple[Step, ...]) -> None:
    """Bringing a `.env` into every lane multiplies the number of places a secret lives.

    Closing the lane removes the worktree, so they go — but a refused or interrupted
    close leaves them. That is not a reason to skip the feature; it is the reason the
    row said so on screen, and this is the same sentence once the answer is given.
    """
    for step in answered:
        if step.verb is Verb.CLONE and looks_like_secrets(step.path):
            context.ui.warn(
                f"{step.path} looks like it holds secrets, and every lane now gets a copy."
            )
            context.ui.detail("  Leave it out in settings · preparation to stop that.")


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
    if effect.verb is Verb.CLONE:
        return lambda: apply.clone(repo / step.path, lane.path / step.path)
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

    if outcome.copied:
        # The user configured this expecting it to be free. It was not.
        ui.warn(f"Copied {subject} — copy-on-write was not possible, so this used real disk")
        ui.detail("  doctor says whether your projects and lanes folders can share blocks.")
        return
    ui.ok(f"Cloned {subject}")
