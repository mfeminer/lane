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
    Command("config", "Read and change what the config screen holds"),
)

SETTINGS = ("projects-root", "lanes-root", "editor")
"""The three flat settings, spelled as the command line spells them.

Kebab on the command line and `projects_root` underneath, which is the one place the
two spellings meet: the underscore form is `Config`'s own field name, the key the
override map uses and the value of the row on the screen, and renaming any of those to
match a command-line convention would be the tail wagging the dog. `cli/configuring.py`
converts, once.
"""


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


def _config_flags(one: argparse.ArgumentParser) -> None:
    """`config`'s own subcommands, and the two that have subcommands of their own.

    The only command with a second level, and it earns it: `config` is four unrelated
    things — three flat settings, a list of prefixes, a per-project checklist and a
    per-project list of commands — where every other subcommand is one. `git config` and
    `gh config` are shaped this way for the same reason, and flattening it would give
    names like `config-prefixes-add`, which is a namespace spelled badly.
    """
    groups = _level(one, "config", dest="config_command", metavar="<what>")

    get = _under(groups, "config", "get", "print one setting's current value")
    _setting(get)

    changing = _under(
        groups, "config", "set", "change one setting, validating it as the screen does"
    )
    _setting(changing)
    changing.add_argument("value", metavar="<value>", nargs="?", help="what to set it to")

    prefixes = _under(
        groups, "config", "prefixes", "the branch prefixes offered when a lane names its branch"
    )
    verbs = _level(prefixes, "config prefixes", dest="config_prefixes_command", metavar="<verb>")
    _under(verbs, "config prefixes", "list", "every prefix, in the order the prompt offers them")
    for verb, description, extra in (
        ("add", "offer one more, after the ones already there", ()),
        ("change", "rename one, in place", ("<new>",)),
        ("forget", "stop offering one", ()),
    ):
        parser = _under(verbs, "config prefixes", verb, description)
        parser.add_argument("prefix", metavar="<prefix>", nargs="?", help="which prefix")
        for name in extra:
            parser.add_argument("to", metavar=name, nargs="?", help="what to call it instead")

    preparing = _under(groups, "config", "preparation", "which ignored paths come into a lane")
    steps = _level(
        preparing, "config preparation", dest="config_preparation_command", metavar="<verb>"
    )
    _project(_under(steps, "config preparation", "list", "every path and what it is answered"))

    answering = _under(steps, "config preparation", "set", "answer one path, or a file of them")
    _project(answering)
    answering.add_argument("--path", metavar="<path>", help="which path, for a single answer")
    # In or out, and nothing else. The third state — *unanswered* — is the absence of a
    # step rather than a value, so there is no flag that could ask for it.
    answer = answering.add_mutually_exclusive_group()
    answer.add_argument(
        "--in", dest="inside", action="store_const", const=True, help="bring it into the lane"
    )
    answer.add_argument(
        "--out", dest="inside", action="store_const", const=False, help="leave it out"
    )
    answering.add_argument(
        "--from-json",
        metavar="<file|->",
        help='answer many at once: [{"path": "…", "answer": "in"|"out"}, …], or - for stdin',
    )
    answering.set_defaults(inside=None)

    commands = _under(groups, "config", "commands", "the commands `run` on every enter of a lane")
    _command_verbs(
        _level(commands, "config commands", dest="config_commands_command", metavar="<verb>")
    )


def _command_verbs(verbs: argparse._SubParsersAction[Any]) -> None:
    """`list`, `add`, `change`, `forget` — the screen's own two verbs plus the two a
    screen gets for free from having a cursor and an `add a command` row."""
    listing = _under(verbs, "config commands", "list", "this project's run steps")
    _project(listing)

    adding = _under(verbs, "config commands", "add", "record one more")
    _project(adding)
    _command_fields(adding)

    changing = _under(
        verbs, "config commands", "change", "edit one — fields not given keep their value"
    )
    _command_id(changing)
    _command_fields(changing)

    forgetting = _under(verbs, "config commands", "forget", "and stop running it")
    _command_id(forgetting)


def _project(one: argparse.ArgumentParser) -> None:
    """Which project's commands. A flag rather than a positional because `list` has
    nothing else to say and `add` has three more things to say after it."""
    one.add_argument("--project", metavar="<name>", help="which project")


def _command_id(one: argparse.ArgumentParser) -> None:
    """`<project>/<command>` — the `<project>/<lane>` shape, one clause different.

    It splits on the **first** slash and takes everything after verbatim, because a
    command routinely contains one (`bin/install`) where a lane name cannot.
    """
    # Its own dest: `command` is already the top-level subcommand's, and `--command` is
    # the field. Three things called `command` on one namespace is one too many.
    one.add_argument("command_id", metavar="<project>/<command>", nargs="?", help="which command")


def _command_fields(one: argparse.ArgumentParser) -> None:
    """The three things a `run` step carries, as the screen asks for them.

    None is `required`: on `add` a missing one is TTY-gated like any other answer, and on
    `change` a missing one means *keep what is stored*, which is what the screen's own
    prompt default already does.
    """
    one.add_argument("--command", dest="run_command", metavar="<cmd>", help="what to run")
    one.add_argument(
        "--directory", metavar="<dir>", help="where to run it, relative to the lane root"
    )
    one.add_argument(
        "--unless", metavar="<path>", help="skip it when this path is already in the lane"
    )


def _setting(one: argparse.ArgumentParser) -> None:
    """Which of the three. Optional to argparse so `--help` is help, not a complaint;
    its absence is refused where the refusal can name all three (`cli.configuring`)."""
    one.add_argument(
        "setting", metavar="<setting>", nargs="?", choices=SETTINGS, help="which setting"
    )


_FLAGS = {
    "open": _open_flags,
    "enter": _enter_flags,
    "close": _close_flags,
    "config": _config_flags,
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:  # noqa: ARG002
        raise UsageError(message or "")


def subparser(*path: str) -> argparse.ArgumentParser:
    """The parser `lane <path…> --help` prints, at whatever depth the path reaches.

    A path rather than a name, because `config` has a level under it and `lane config
    prefixes --help` has to be that screen's help rather than `config`'s. Nothing here
    knows how deep any particular command goes: it walks whatever subparsers it finds.
    """
    found = build()
    for name in path:
        nested: argparse.ArgumentParser | None = _subparsers(found).choices.get(name)
        if nested is None:  # pragma: no cover - every caller passes a parsed name
            raise KeyError(name)
        found = nested
    return found


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction[Any]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("the parser has no subcommands")  # pragma: no cover


def _level(
    parser: argparse.ArgumentParser, path: str, *, dest: str, metavar: str
) -> argparse._SubParsersAction[Any]:
    """Open a level of subcommands under `parser`, each `<prog>` naming its full path."""
    return parser.add_subparsers(
        dest=dest, metavar=metavar, parser_class=_Parser, prog=f"{buildinfo.APP} {path}"
    )


def _under(
    groups: argparse._SubParsersAction[Any], path: str, name: str, description: str
) -> argparse.ArgumentParser:
    """One nested subcommand, with the two flags every one of them has.

    `--help` and `--json` are added here rather than repeated per command, for the same
    reason the top level adds them in a loop: a subcommand that forgot either would be a
    hole nobody notices until somebody pipes it.
    """
    one: argparse.ArgumentParser = groups.add_parser(
        name, help=description, description=description, add_help=False
    )
    one.add_argument("-h", "--help", action="store_true", help="print this message")
    one.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=_JSON_HELP)
    one.set_defaults(help_for=(*path.split(), name))
    return one


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
