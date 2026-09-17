"""One function per subcommand: translate flags into answers, then run the action.

**No subcommand decides anything.** Each one turns its flags into the answers the
interactive flow would have been given, hands them to `Prefilled`, and calls the
very same action the menu calls. What a subcommand owns is the translation and the
exit code — never the behaviour.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence

from lane import app, buildinfo, cli
from lane.actions import picking
from lane.cli import emit
from lane.cli.answers import NeedsAnswer, NoSuchOption, Prefilled
from lane.context import Context
from lane.environment import Environment
from lane.lanes import Lane
from lane.ui.console_ui import ConsoleUi
from lane.ui.seam import Node


class Unusable(Exception):
    """The command line contradicts itself. Refused before anything is asked or done."""


class NotThere(Exception):
    """A name the command line gave that nothing answers to. Exit 4.

    The base of every "no such …" a subcommand can raise, so the dispatcher catches one
    thing rather than growing a tuple that a new subcommand can forget to join."""


def run(args: argparse.Namespace, environment: Environment) -> int:
    # In `--json` mode everything lane says moves to stderr — the spinner, the `✓`,
    # the refusal, and any prompt it still has to draw — so that stdout is one JSON
    # document and nothing else.
    ui = ConsoleUi(to_stderr=_wants_json(args))
    wiring = app.wire(environment, ui)

    if wiring.context is None:
        # The same refusal the session gives, by the same route: nothing lane does
        # works until the config can be read, and this is not a subcommand's own
        # opinion about that.
        assert wiring.problem is not None
        ui.error(wiring.problem)
        ui.detail("  Fix or delete that file, then run lane again.")
        return cli.EXIT_REFUSED

    if wiring.notice is not None:
        ui.detail(wiring.notice)

    context = wiring.context

    try:
        return _COMMANDS[args.command](context, args)
    except Unusable as exc:
        return _refuse(exc, cli.EXIT_USAGE)
    except NeedsAnswer as exc:
        # The second line is the useful half: which flag would have answered it, or —
        # where no flag can — what to do instead.
        if exc.flag:
            said = "was not accepted" if exc.spent else "would answer it"
            return _refuse(exc, cli.EXIT_NO_TTY, f"{exc.flag} {said}.")
        return _refuse(exc, cli.EXIT_NO_TTY, exc.remedy)
    except (NoSuchOption, NoSuchLane, NotThere) as exc:
        # One exit code for every "you named something that is not there", whether it is
        # a lane, a project, a branch or a prefix. A script branches on 4 and reads the
        # message for which; a code per kind would be a table nobody could remember.
        return _refuse(exc, cli.EXIT_NOT_FOUND)


def _refuse(exc: Exception, code: int, detail: str = "") -> int:
    """Every refusal the command line itself makes, in one shape and on stderr.

    On stderr in both modes, unlike lane's own prose: this is the command line
    answering about the command line, and a caller reading JSON still has to be able
    to read it.
    """
    print(f"{buildinfo.APP}: {exc}", file=sys.stderr)
    if detail:
        print(f"  {detail}", file=sys.stderr)
    return code


def prefilled(
    context: Context,
    script: dict[str, object],
    flags: dict[str, str],
    *,
    remedies: dict[str, str] | None = None,
) -> Prefilled:
    """The prompt layer, with whatever the command line already answered in it.

    Set by the commands that ask something, once, wrapping the real `Ui` the context
    was wired with. The two that ask nothing — `list` and `doctor` — leave it alone
    rather than wrapping a prompt layer around a screen that has no prompts.
    """
    return Prefilled(
        script,
        context.ui,
        interactive=context.environment.is_interactive(),
        flags=flags,
        remedies=remedies,
    )


def _open(context: Context, args: argparse.Namespace) -> int:
    """`lane open`, answered in advance.

    Every flag here is one keystroke of the interactive flow written down. `--branch-name`
    is two, because that is what it is: the `other…` entry of the branch menu, and then
    the name typed into the prompt behind it.
    """
    from lane.actions import open_lane

    script: dict[str, object] = {}
    if args.project is not None:
        script[picking.PROJECT] = args.project
    if args.description is not None:
        script[open_lane.KIND] = open_lane.NEW
        script[open_lane.DESCRIPTION] = args.description
        # `--mode` defaults to what the menu lists first, and an unnamed branch to the
        # first prefix on offer — neither written down here, because both belong to a
        # screen (and the prefixes are a setting). A default belongs to the path its
        # flag selects: with no `--description` the kind is still an open question, and
        # answering the mode of a path nobody has chosen yet answers ahead of the user.
        script[open_lane.MODE] = args.mode or Prefilled.DEFAULT
        if args.branch_name is None and args.mode != "detached":
            script[open_lane.BRANCH_NAME] = Prefilled.DEFAULT
    if args.branch is not None:
        script[open_lane.KIND] = open_lane.EXISTING
        script[open_lane.BRANCH] = args.branch
        # The adopt path asks for a lane name, offering the branch's slug. Taking the
        # prompt's own default is what pressing Enter there would do — and it keeps
        # slugify's rules in one place rather than reimplementing them out here.
        script[open_lane.LANE_NAME] = Prefilled.DEFAULT
    elif args.mode is not None:
        script[open_lane.MODE] = args.mode
    if args.branch_name is not None:
        script[open_lane.BRANCH_NAME] = open_lane.OTHER
        script[open_lane.BRANCH_NAME_TYPED] = args.branch_name
    if args.lane_name is not None:
        script[open_lane.LANE_NAME] = args.lane_name

    _refuse_contradictions(args)
    context.ui = prefilled(context, script, _OPEN_FLAGS)

    opened = open_lane.open_a_lane(context, launch_editor=args.launch_editor)
    if opened is None:
        return cli.EXIT_REFUSED

    if _wants_json(args):
        emit.emit(
            {
                "project": opened.project,
                "lane": opened.lane,
                "slug": f"{opened.project}/{opened.lane}",
                "path": str(opened.path),
                "branch": opened.branch,
                "detached": opened.branch is None,
                "adopted": opened.adopted,
                "base": opened.base,
                "start": opened.start,
                "editor": {
                    "launched": opened.entered.launched,
                    "detail": opened.entered.editor,
                },
            }
        )
    return cli.EXIT_OK


_OPEN_FLAGS = {
    picking.PROJECT: "--project",
    "kind": "--description or --branch",
    "description": "--description",
    "mode": "--mode",
    "branch-name": "--branch-name",
    "branch-name-typed": "--branch-name",
    "branch": "--branch",
    "lane-name": "--lane-name",
}
"""Which flag would have answered which question, so a refusal can name it."""


def _refuse_contradictions(args: argparse.Namespace) -> None:
    """Flags that cannot both be meant. A usage error, never a silent no-op.

    argparse already refuses `--description` with `--branch`. What it cannot see is
    that the second path has no mode and no branch to name: adopting a branch *is*
    the branch, and detached is the opposite of adopting one.
    """
    if args.branch is not None and args.mode is not None:
        raise Unusable("--mode does not apply to --branch: an adopted branch is not detached")
    if args.branch is not None and args.branch_name is not None:
        raise Unusable("--branch-name does not apply to --branch: the branch is already named")
    if args.mode == "detached" and args.branch_name is not None:
        raise Unusable("--branch-name does not apply to --mode detached: there is no branch")


def _enter(context: Context, args: argparse.Namespace) -> int:
    """`lane enter demo/pager`: the listing's own slug, then the listing's own verb."""
    from lane.actions import enter_lane

    lane = _find(context, args.lane)
    context.ui = prefilled(context, {}, {}, remedies=_PREPARATION_REMEDY)

    entered = enter_lane.enter(context, lane, launch_editor=args.launch_editor)
    if _wants_json(args):
        emit.emit(
            {
                "slug": lane.slug,
                "path": str(lane.path),
                "prepared": {
                    "cloned": list(entered.prepared.cloned),
                    "ran": list(entered.prepared.ran),
                    "skipped": list(entered.prepared.skipped),
                    "failed": [
                        {"step": step, "detail": detail} for step, detail in entered.prepared.failed
                    ],
                },
                "editor": {"launched": entered.launched, "detail": entered.editor},
            }
        )
    return cli.EXIT_REFUSED if entered.prepared.failed else cli.EXIT_OK


_PREPARATION_REMEDY = {
    "preparation": (
        "Answer those paths once — enter the lane in a terminal, or open "
        "config · preparation — and this lane and every other will remember."
    )
}
"""Entering a lane can ask **one** thing, and no flag answers it.

Deciding it here would be the wrong kind of convenience: bringing an unanswered path
in copies what nobody asked for (a `.env` is exactly the sort of path that turns up
unanswered), and leaving it out exits 0 on a lane that is not ready. Both are silent.
So it refuses, before applying anything, and says where the answer belongs.
"""


def _close(context: Context, args: argparse.Namespace) -> int:
    """`lane close demo/pager`, answered against the screen's own rows.

    Which rows a close has is a fact about *this* lane — whether anything is stranded,
    which branches it wandered through and left work on — so the flags cannot be
    checked until the screen is built. They are checked there, against exactly what it
    would have drawn, and a flag naming something it does not offer is refused before
    anything is removed.
    """
    from lane.actions import close_lane

    lane = _find(context, args.lane)
    _refuse_a_half_answered_close(args)

    script: dict[str, object] = {}
    if args.yes:
        script[close_lane.SCREEN] = _decide_the_close(args)
    context.ui = prefilled(context, script, {}, remedies={close_lane.SCREEN: _CLOSE_REMEDY})

    closed = close_lane.close(context, lane)
    if _wants_json(args):
        emit.emit(
            {
                "slug": closed.slug,
                "closed": closed.closed,
                "refusal": closed.refusal,
                "found": {"issues": list(closed.issues), "clean": list(closed.clean)},
                "decided": {
                    "rescue": closed.rescued,
                    "delete_others": list(closed.delete_others),
                },
                "branches_deleted": list(closed.deleted),
                "branches_kept": list(closed.kept),
            }
        )
    return cli.EXIT_OK if closed.closed else cli.EXIT_REFUSED


_CLOSE_REMEDY = (
    "--yes accepts this close, taking every default the screen starts with: rescue "
    "what would be stranded, delete what goes anyway, keep what holds unique work."
)


def _refuse_a_half_answered_close(args: argparse.Namespace) -> None:
    """A row flag with no `--yes` has nothing to accept it, and there is no half state.

    The alternative — pre-answering the rows and still drawing the screen — reads well
    until you are in a pipe, where the screen cannot be drawn and the flags would then
    mean something different from what they meant a moment ago. One meaning each.
    """
    if args.yes:
        return
    named = [
        flag
        for flag, given in (
            ("--rescue/--no-rescue", args.rescue is not None),
            ("--delete-branch/--keep-branch", args.delete_branch is not None),
            ("--delete-others", args.delete_others is not None),
            ("--keep-others", args.keep_others),
        )
        if given
    ]
    if named:
        raise Unusable(
            f"{', '.join(named)} says what closing does, and --yes is what accepts it. "
            f"Add --yes, or leave them all out and answer the screen."
        )


def _decide_the_close(args: argparse.Namespace) -> Callable[..., Mapping[object, bool]]:
    """Turn the flags into answers, against the rows the screen would have drawn."""
    from lane.actions.close_lane import Delete, Rescue

    wanted = [name for name in (args.delete_others or "").split(",") if name]

    def decide(
        nodes: Sequence[Node[object]], defaults: Mapping[object, bool]
    ) -> dict[object, bool]:
        answers = dict(defaults)
        values = [node.row.value for node in nodes]
        rescues = [value for value in values if isinstance(value, Rescue)]
        own = [value for value in values if isinstance(value, Delete) and value.own]
        others = {
            value.branch: value for value in values if isinstance(value, Delete) and not value.own
        }

        if args.rescue is not None:
            if not rescues:
                raise Unusable(
                    "--rescue does not apply to this lane: nothing would be stranded by "
                    "closing it, so the close never offers to park anything"
                )
            answers[rescues[0]] = args.rescue

        if args.delete_branch is False and not own:
            # `--keep-branch` asks for a deviation, so it needs a row to deviate from.
            # `--delete-branch` does not: deleting every branch it can is what closing
            # already does, so with no row it is redundant rather than wrong.
            raise Unusable(
                "--keep-branch does not apply to this close: it asks nothing about the "
                "lane's own branch, which either goes with the lane or does not exist"
            )
        for value in own:
            if args.delete_branch is not None:
                answers[value] = args.delete_branch

        for named in wanted:
            if named not in others:
                offered = ", ".join(sorted(others)) or "no branch it used earlier"
                raise Unusable(
                    f"--delete-others names '{named}', which this close does not offer: "
                    f"it asks about {offered}"
                )
            answers[others[named]] = True
        if args.keep_others:
            for value in others.values():
                answers[value] = False
        return answers

    return decide


def _find(context: Context, slug: str | None) -> Lane:
    """The lane a `<project>/<lane>` slug names.

    One identifier, and it is the one the listing already prints on every row. A bare
    lane name is refused rather than guessed at: a lane name is unique inside its
    project and nowhere else, so resolving one would mean picking for the user.
    """
    if not slug:
        raise Unusable("name the lane to act on, as <project>/<lane> — 'lane list' shows them")
    project, separator, name = slug.partition("/")
    if not separator or not project or not name or "/" in name:
        raise Unusable(f"'{slug}' is not a lane — name one as <project>/<lane>, like demo/pager")

    for lane in context.lane_store().list_lanes():
        if lane.project == project and lane.name == name:
            return lane
    raise NoSuchLane(slug)


class NoSuchLane(NotThere):
    """No lane of that name is open."""

    def __init__(self, slug: str) -> None:
        super().__init__(f"no open lane called '{slug}' — 'lane list' shows the ones there are")
        self.slug = slug


def _list(context: Context, args: argparse.Namespace) -> int:
    """Every open lane. **It prints; it never opens the screen you stand in.**

    The table in the menu offers `enter` and `close` for the row under the cursor,
    which is acting rather than looking — and this subcommand is read-only by
    contract. Printing also means one behaviour to describe instead of two, in a pipe
    and in a terminal alike. What it shares with the screen is everything that
    decides the content: the same rows, the same cells, the same `gh` answers.
    """
    from lane.actions import list_lanes

    lanes = context.lane_store().list_lanes()
    table = list_lanes.Table(context, lanes, {})
    if lanes:
        context.ui.progress("Reading lane status…", table.settle)

    if _wants_json(args):
        emit.emit([_lane_json(row) for row in table.surveyed()])
        return cli.EXIT_OK

    if not lanes:
        # The empty state the listing already has, in the same words (§12).
        context.ui.detail("No open lanes. Open one with: lane open")
        return cli.EXIT_OK

    context.ui.table(table.title, list_lanes.COLUMNS, table.rows())
    return cli.EXIT_OK


def _lane_json(row: object) -> dict[str, object]:
    """One lane, as the listing knows it.

    **Additive only, once shipped**: a field is added, never removed or renamed, and
    never changed in meaning — a script reading `merged` next year must get the same
    answer to the same question (clig.dev, and AGENTS.md).
    """
    from lane.actions.list_lanes import LaneRow

    assert isinstance(row, LaneRow)
    lane, status = row.lane, row.status
    found = {
        "project": lane.project,
        "name": lane.name,
        "slug": lane.slug,
        "path": str(lane.path),
        "description": lane.meta.description,
        "age_days": lane.age_days(),
        "problem": row.problem or None,
    }
    if status is None:
        return found | {
            "branch": None,
            "detached": None,
            "dirty": None,
            "unpushed": None,
            "merged": None,
            "pull_request": None,
            "stacked": [],
        }
    return found | {
        "branch": status.branch,
        "detached": status.detached,
        "dirty": status.dirty_count,
        "unpushed": status.unpushed_count,
        "upstream": status.upstream,
        "merged": status.landed or (row.pr.merged and status.has_own_commits),
        "pull_request": {
            "state": row.pr.state,
            "number": row.pr.number,
            "url": row.pr.url,
            "detail": _pr_detail(row.pr),
        },
        "stacked": list(row.pr.stacked),
    }


def _pr_detail(cell: object) -> str:
    """The panel's one sentence, trimmed of the punctuation that joins it to a screen."""
    from lane.actions.list_lanes import PrCell

    assert isinstance(cell, PrCell)
    return cell.note.split(",")[0].rstrip(".")


def _doctor(context: Context, args: argparse.Namespace) -> int:
    from lane.actions import doctor

    if not _wants_json(args):
        doctor.run(context)
        return cli.EXIT_OK

    found = doctor.checks(context)
    emit.emit(
        {
            "ok": all(check.status == "ok" for check in found),
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "report": [line.text.strip() for line in check.lines],
                    "facts": dict(check.facts),
                }
                for check in found
            ],
        }
    )
    return cli.EXIT_OK


def _wants_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


def _config(context: Context, args: argparse.Namespace) -> int:
    """`lane config …`, which lives in its own module — it is four groups, not one."""
    from lane.cli import configuring

    return configuring.run(context, args)


_COMMANDS = {
    "open": _open,
    "list": _list,
    "enter": _enter,
    "close": _close,
    "doctor": _doctor,
    "config": _config,
}
