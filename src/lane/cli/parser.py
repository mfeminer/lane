"""The command line, generated from one table — and `--help` with it.

**Nothing here imports an action.** `--version` and `--help` are answered before any
prerequisite is consulted, so the parser has to be buildable on a machine where
nothing lane needs is installed, and without paying for the UI stack. The commands
are imported by name when one is actually run (`cli.commands`).

The help text is `argparse`'s own. It used to be a hand-written paragraph, and that
was right when there were two flags to describe and the useful half of the text was
"there is nothing else to type" — but five subcommands with their own flags each is
exactly the kind of list that drifts from the code when a person maintains it. One
definition, two readers: the parser and the reader of `--help`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, NoReturn

from lane import buildinfo


class UsageError(Exception):
    """argparse wanted to exit. lane prints its own prose and chooses its own code."""


@dataclass(frozen=True, slots=True)
class Command:
    """One subcommand: its name, its one-line description, and what it needs.

    A second table beside `actions.ACTIONS`, deliberately — see AGENTS.md. The menu
    is the interactive session's list and this is the scriptable one; they overlap
    without being the same set, and what they **share is the action function**, which
    is the only thing that could have drifted.
    """

    name: str
    description: str
    takes_lane: bool = False
    """Needs a `<project>/<lane>` on the command line. A script has no cursor."""


COMMANDS: tuple[Command, ...] = (
    Command("open", "Open a lane: new work, or a branch that already exists"),
    Command("list", "Every open lane, where it stands, and what to do with it"),
    Command("enter", "Bring a lane up to date, then open the editor in it", takes_lane=True),
    Command("close", "Safety checks, then remove the worktree", takes_lane=True),
    Command("doctor", "Check git, gh, the editor and your paths"),
)


_JSON_HELP = "print the outcome as JSON on stdout, and nothing else there"


def _nothing(one: argparse.ArgumentParser) -> None:
    """A subcommand with no flags of its own beyond `--json`."""


def _open_flags(one: argparse.ArgumentParser) -> None:
    """Everything `open_lane._gather` asks, as flags.

    None of them is `required=True`, deliberately: a missing answer is **TTY-gated**,
    not flag-gated, so `lane open` at a terminal still asks the question the session
    would have asked. Required means required *when scripting*, and that is enforced
    where it is true — by the refusal that names the flag (`cli.answers`).
    """
    one.add_argument("--project", metavar="<name>", help="which project the lane is in")

    # The interactive fork, as a pair of flags: new work, or a branch already there.
    kind = one.add_mutually_exclusive_group()
    kind.add_argument("--description", metavar="<text>", help="new work: what this lane is for")
    kind.add_argument("--branch", metavar="<name>", help="adopt a branch that already exists")

    one.add_argument(
        "--mode",
        choices=("branch", "detached"),
        help="new work: start on a branch (the default) or detached",
    )
    one.add_argument(
        "--branch-name",
        metavar="<name>",
        help="new work: the branch to create, instead of the prefix-derived default",
    )
    one.add_argument(
        "--lane-name",
        metavar="<name>",
        help="the lane's directory name, instead of the one derived from the description or branch",
    )
    one.add_argument(
        "--launch-editor",
        action="store_true",
        help="open the editor in the lane (off from the command line, on in a session)",
    )


def _enter_flags(one: argparse.ArgumentParser) -> None:
    one.add_argument(
        "--launch-editor",
        action="store_true",
        help="open the editor in the lane (off from the command line, on in a session)",
    )


def _close_flags(one: argparse.ArgumentParser) -> None:
    """The close screen's rows, as flags — and `--yes`, which accepts the screen.

    Row flags say what closing *does*; `--yes` says to do it. They are separable on
    purpose: accepting a close is itself a decision, and no amount of detail about
    the rows amounts to having taken it.
    """
    rescue = one.add_mutually_exclusive_group()
    rescue.add_argument(
        "--rescue",
        dest="rescue",
        action="store_const",
        const=True,
        help="park commits stranded on a detached HEAD (only where that is offered)",
    )
    rescue.add_argument(
        "--no-rescue", dest="rescue", action="store_const", const=False, help="let them go"
    )

    branch = one.add_mutually_exclusive_group()
    branch.add_argument(
        "--delete-branch",
        dest="delete_branch",
        action="store_const",
        const=True,
        help="delete the lane's branch even where git would refuse",
    )
    branch.add_argument(
        "--keep-branch",
        dest="delete_branch",
        action="store_const",
        const=False,
        help="keep it instead",
    )

    others = one.add_mutually_exclusive_group()
    others.add_argument(
        "--delete-others",
        metavar="<branch,branch>",
        help="also delete these branches the lane used earlier and left work on",
    )
    others.add_argument(
        "--keep-others", action="store_true", help="keep every branch the lane used earlier"
    )

    one.add_argument(
        "--yes",
        action="store_true",
        help="accept the close, taking every default the screen would have started with",
    )
    one.set_defaults(rescue=None, delete_branch=None)


_FLAGS = {"open": _open_flags, "enter": _enter_flags, "close": _close_flags}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:  # noqa: ARG002
        raise UsageError(message or "")


def subparser(name: str) -> argparse.ArgumentParser:
    """One subcommand's own parser, which is what `lane <command> --help` prints."""
    found: argparse.ArgumentParser | None = _subparsers(build()).choices.get(name)
    if found is None:  # pragma: no cover - every caller passes a name from COMMANDS
        raise KeyError(name)
    return found


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction[Any]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("the parser has no subcommands")  # pragma: no cover


def build() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=buildinfo.APP,
        description=(
            f"{buildinfo.APP} — run several pieces of work side by side, "
            "each in its own git worktree"
        ),
        epilog=(
            f"Run '{buildinfo.APP}' with no arguments to start an interactive session: "
            f"it shows a menu of everything it can do. A terminal is required for that. "
            f"A subcommand runs anywhere, and refuses by name if it needs an answer no "
            f"flag gave it."
        ),
        add_help=False,
    )
    parser.add_argument("-V", "--version", action="store_true", help="print the version and build")
    parser.add_argument("-h", "--help", action="store_true", help="print this message")

    # `--json` is global in the sense that matters: every subcommand has it. It is
    # accepted on either side of the subcommand (`lane --json list`, `lane list
    # --json`) because both read naturally and refusing one would be a footgun;
    # SUPPRESS on the subcommand copy is what stops it overwriting the other.
    parser.add_argument("--json", action="store_true", help=_JSON_HELP)

    subparsers = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
    for command in COMMANDS:
        one = subparsers.add_parser(
            command.name,
            help=command.description,
            description=command.description,
            add_help=False,
        )
        one.add_argument("-h", "--help", action="store_true", help="print this message")
        one.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=_JSON_HELP)
        if command.takes_lane:
            # Optional to argparse so that `lane close --help` is help rather than a
            # complaint about a missing argument. Its absence is refused where the
            # refusal can say something useful (`cli.commands`).
            one.add_argument("lane", metavar="<project>/<lane>", nargs="?", help="which lane")
        _FLAGS.get(command.name, _nothing)(one)

    return parser
