"""`lane config`, as a caller of the screens rather than a second way to configure.

The same rule the core-loop subcommands follow (`cli/commands.py`), applied to the one
action that was deliberately left out of them: **nothing here decides anything.** A
`set` answers the question `actions/config.py` was going to ask and then lets that
module ask it, so a projects root with no repositories is refused by the same code that
refuses it on screen, and the write goes through the same `ConfigStore`. What this
module owns is the translation, the identifier, the JSON and the exit code.

It is its own module rather than more of `cli/commands.py` because `config` is the only
subcommand with a level under it — four groups, each with its own verbs — and because
`commands.py` was already the longest thing in `cli/`.

**Not `cli/config.py`.** Two modules are called `config` already (`lane/config.py` is
the store, `actions/config.py` is the screen); a third would be one too many for a
reader holding all of them at once.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lane import cli
from lane.actions.config import remember_answers as screen_remember
from lane.cli import emit
from lane.cli.commands import NotThere
from lane.cli.parser import SETTINGS
from lane.context import Context
from lane.prepare import Step, Verb

UNDERSCORED = {name: name.replace("-", "_") for name in SETTINGS}
"""`projects-root` → `projects_root`: the command line's spelling to everything else's.

The one place the two meet. `Config`'s fields, the override map's keys and the screen's
row values are all the underscored form, and the kebab form is the command line's own
convention — so this converts rather than renaming either side to suit the other.
"""


def run(context: Context, args: argparse.Namespace) -> int:
    from lane.cli.commands import Unusable

    group = getattr(args, "config_command", None)
    if group is None:
        raise Unusable(
            "say what to configure: " + ", ".join(_GROUPS) + " — see 'lane config --help'"
        )
    return _GROUPS[group](context, args)


def _get(context: Context, args: argparse.Namespace) -> int:
    """One setting's current value — what lane would actually use, not what the file says.

    The environment wins over the file everywhere else in lane, so it wins here: a `get`
    reporting the file's value while lane used the variable's would be a reading of a
    config nobody is running. Which one it came from is the `overridden_by` field, so a
    script never has to infer it.
    """
    key = _named(args)
    value = _value(context, key)

    if _wants_json(args):
        emit.emit(_report(context, key, value))
        return cli.EXIT_OK

    # The value alone, so `$(lane config get editor)` needs no trimming. Where it came
    # from goes to stderr, which is where everything that is not the answer belongs.
    print(value if value is not None else "not set")
    if (variable := context.overridden.get(UNDERSCORED[key])) is not None:
        context.ui.detail(f"  {variable} overrides {key}")
    return cli.EXIT_OK


def _set(context: Context, args: argparse.Namespace) -> int:
    """Change one setting, by answering the question the screen was going to ask.

    **The environment is not special-cased.** If a variable is currently winning, this
    still writes the file — which is exactly what the screen does, and for the same
    reason: the file is the thing lane can edit. What it adds is saying so, in the line
    it prints and in `overridden_by`, so a caller can tell a write that has not taken
    effect yet from one that has without parsing prose.
    """
    from lane.actions import config as screen
    from lane.cli.commands import Unusable, prefilled

    key = _named(args)
    value: str | None = getattr(args, "value", None)
    if value is None:
        raise Unusable(f"say what to set {key} to: lane config set {key} <value>")

    setting = UNDERSCORED[key]
    # Not a flag but a positional, so the refusal names the whole command: "--project
    # was not accepted" would be pointing at something that was never typed.
    named = f"the value given to 'lane config set {key}'"
    context.ui = prefilled(context, {setting: value}, {setting: named})
    if not screen.change_setting(context, setting):
        return cli.EXIT_REFUSED

    saved = _value(context, key)
    variable = context.overridden.get(setting)
    if _wants_json(args):
        emit.emit(_report(context, key, saved))
    else:
        context.ui.ok(f"{key} = {value}")
    if variable is not None:
        # Said in both modes: a write that silently does not take effect is the one
        # thing this command could do that reads as a bug.
        context.ui.warn(f"{variable} overrides {key}, so the environment still wins.")
        context.ui.detail(f"  Unset it to use what was just saved: unset {variable}")
    return cli.EXIT_OK


def _prefixes(context: Context, args: argparse.Namespace) -> int:
    """The branch prefixes: the same four things the screen does, named instead of pointed at.

    `change`/`forget` are the screen's own verbs, unchanged — `lane config prefixes
    change feature story` is that screen's two keystrokes written down, the verb and
    then the name typed into the prompt behind it.
    """
    from lane.actions import config as screen
    from lane.cli.commands import Unusable, prefilled

    verb = getattr(args, "config_prefixes_command", None)
    if verb is None:
        raise Unusable("say what to do with the prefixes: list, add, change, forget")

    store = context.prefix_store()
    if verb == "list":
        return _prefixes_report(context, args)

    prefix: str | None = getattr(args, "prefix", None)
    if prefix is None:
        raise Unusable(f"name the prefix to {verb}: lane config prefixes {verb} <prefix>")

    if verb == "add":
        context.ui = prefilled(context, {screen.PREFIX: prefix}, _PREFIX_FLAGS)
        if not screen.add_prefix(context):
            return cli.EXIT_REFUSED
        return _prefixes_report(context, args)

    # `change` and `forget` act on a row, so the row has to exist. The screen resolves
    # that with a cursor and cannot get it wrong; a script names it, which can be a typo
    # or a stale assumption — the same mistake `lane enter` makes about a lane.
    if prefix not in store.load():
        raise NoSuchPrefix(prefix, store.load())

    script: dict[str, object] = {screen.PREFIX_VERB: verb}
    if verb == "change":
        changed: str | None = getattr(args, "to", None)
        if changed is None:
            raise Unusable(
                f"say what to call it instead: lane config prefixes change {prefix} <new>"
            )
        script[screen.PREFIX] = changed

    context.ui = prefilled(context, script, _PREFIX_FLAGS)
    if not screen.act_on_prefix(context, prefix):
        return cli.EXIT_REFUSED
    return _prefixes_report(context, args)


def _prefixes_report(context: Context, args: argparse.Namespace) -> int:
    """Every prefix after the write, never just the one that changed.

    The order **is** the branch prompt's menu, so what a caller needs back is the menu —
    and a rename that moved a row would be invisible in a report naming one prefix.
    """
    store = context.prefix_store()
    offered = list(store.load())

    if _wants_json(args):
        emit.emit(
            {
                "prefixes": offered,
                "path": str(store.path),
                # Whether these are the six lane ships with or a list somebody chose.
                # The store answers it: an absent *or* empty file means the seed, which
                # comparing against DEFAULT_PREFIXES would get wrong for anybody who
                # wrote the same six down on purpose.
                "seeded": not store.customised(),
            }
        )
        return cli.EXIT_OK

    if getattr(args, "config_prefixes_command", None) == "list":
        for prefix in offered:
            print(f"{prefix}/")
    return cli.EXIT_OK


_PREFIX_FLAGS = {
    "prefix": "the prefix given",
    "prefix-verb": "the verb given",
}
"""What a refusal names when one of these questions comes round again — which happens
when the validation behind it refused the value (`cli/answers.py`, *spent*)."""


class NoSuchPrefix(NotThere):
    """A prefix that is not on the menu. Exit 4, like any other name that is not there."""

    def __init__(self, prefix: str, offered: tuple[str, ...]) -> None:
        super().__init__(
            f"'{prefix}' is not offered — there is {', '.join(offered)}"
            if offered
            else f"'{prefix}' is not offered"
        )
        self.prefix = prefix


def _preparation(context: Context, args: argparse.Namespace) -> int:
    """Which ignored paths come into a lane, for one project.

    **This shows more than the screen does, and the difference is deliberate.**
    `config · preparation` lists only paths somebody has already answered — it is a
    review screen, and entering a lane is what discovers new ones. A script needs the
    unanswered ones too: to see that `cache/` has never been decided, and because `set`
    has to be able to say a path is a typo rather than filing an answer against a path
    this project does not have. So this asks git the same question entering a lane asks
    (`ignored_paths`) and reports the union — what was discovered and what was answered.
    """
    from lane.cli.commands import Unusable

    verb = getattr(args, "config_preparation_command", None)
    if verb is None:
        raise Unusable("say what to do with the preparation answers: list, set")

    project = _a_project(context, args)
    if verb == "list":
        return _preparation_report(context, args, project)
    return _preparation_set(context, args, project)


def _preparation_set(context: Context, args: argparse.Namespace, project: str) -> int:
    """Answer one path or a file of them — **the same call, with one entry or many.**

    One code path for "one" and "many" on purpose: a single `--path` is a batch of one,
    so the validation, the write and the reporting cannot drift between them.
    """
    from lane.cli.commands import Unusable

    wanted = _entries(args)
    if not wanted:
        raise Unusable("say what to answer: --path <path> --in|--out, or --from-json <file|->")

    store = context.prepare_store()
    remembered = store.load()
    discovered = _discovered(context, project)

    applied: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    steps: list[Step] = []
    for path, inside in wanted:
        if path not in discovered:
            # A per-entry error, never a reason to abandon the batch: "some of two
            # hundred were typos" is exactly the case this command exists to answer, and
            # the useful answer is the good ones landing and the bad ones named.
            rejected.append({"path": path, "reason": f"not an ignored path in {project}"})
            continue
        steps.append(Step(project=project, verb=Verb.CLONE if inside else Verb.SKIP, path=path))
        applied.append({"path": path, "answer": "in" if inside else "out"})

    if steps:
        # One write for the whole batch, through the very function the screen writes
        # with. The rejected entries contributed nothing to it, so a file half-written
        # from a bad batch is not a state that can exist.
        screen_remember(store, remembered.steps, steps)

    if _wants_json(args):
        emit.emit({"project": project, "applied": applied, "rejected": rejected})
    else:
        for one in applied:
            context.ui.ok(f"{project}/{one['path']} — {one['answer']}")
        for one in rejected:
            context.ui.error(f"{project}/{one['path']} — {one['reason']}")
    return cli.EXIT_REFUSED if rejected else cli.EXIT_OK


def _entries(args: argparse.Namespace) -> list[tuple[str, bool]]:
    """What was asked for, from a flag or from a file — one shape either way."""
    from lane.cli.commands import Unusable

    source: str | None = getattr(args, "from_json", None)
    path: str | None = getattr(args, "path", None)
    inside: bool | None = getattr(args, "inside", None)

    if source is not None and path is not None:
        raise Unusable("--path and --from-json both say which paths; give one or the other")

    if source is not None:
        return _from_json(source)

    if path is None:
        return []
    if inside is None:
        # A path is in or out, and nothing else. The third state is the *absence* of an
        # answer, which is a deletion rather than a value — so no flag can ask for it.
        raise Unusable(f"say whether {path} comes in: --in or --out")
    return [(path, inside)]


def _from_json(source: str) -> list[tuple[str, bool]]:
    """`[{"path": "…", "answer": "in"|"out"}, …]`, from a file or from stdin.

    A malformed document is refused whole, unlike a bad *entry*: an entry lane cannot
    read is a typo in one row, and a document it cannot parse is a caller that has not
    produced the thing it thinks it has.
    """
    import json
    import sys

    from lane.cli.commands import Unusable

    try:
        raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise Unusable(f"could not read {source}: {exc}") from exc

    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise Unusable(f"{source} is not valid JSON: {exc}") from exc

    if not isinstance(body, list):
        raise Unusable(f'{source} must be a list of {{"path": …, "answer": "in"|"out"}}')

    wanted: list[tuple[str, bool]] = []
    for index, entry in enumerate(body):
        if not isinstance(entry, dict):
            raise Unusable(f"{source}: entry {index} is not an object")
        path, answer = entry.get("path"), entry.get("answer")
        if not isinstance(path, str) or answer not in {"in", "out"}:
            raise Unusable(
                f'{source}: entry {index} needs a "path" and an "answer" of "in" or "out"'
            )
        wanted.append((path, answer == "in"))
    return wanted


def _preparation_report(context: Context, args: argparse.Namespace, project: str) -> int:
    """Every path this project has an answer or a discovery for, and where it stands."""
    remembered = context.prepare_store().load().for_project(project)
    stored = {step.path: step for step in remembered if step.path}
    discovered = _discovered(context, project)
    inside = _in_a_lane(context, project)

    found: list[dict[str, object]] = []
    for path in sorted(set(discovered) | set(stored), key=str.lower):
        step = stored.get(path)
        found.append(
            {
                "path": path,
                # The checklist's three states, as data. `unset` is the one two states
                # could not say — a path deliberately kept out and one never asked about
                # used to render identically.
                "answer": "unset" if step is None else ("in" if step.verb is Verb.CLONE else "out"),
                # False for a path git no longer reports: the answer is still real and
                # still stored, and dropping it from the listing would hide a row that
                # `forget` would still have something to say about.
                "discovered": path in discovered,
                "present_in_a_lane": path in inside,
            }
        )

    if _wants_json(args):
        emit.emit({"project": project, "paths": found})
        return cli.EXIT_OK

    for one in found:
        where = " · in a lane" if one["present_in_a_lane"] else ""
        print(f"{one['answer']:>5}  {one['path']}{where}")
    return cli.EXIT_OK


def _discovered(context: Context, project: str) -> set[str]:
    """What git reports as ignored in the project's main clone, where the files are.

    The same backend call entering a lane makes, so the two agree about what a path even
    is — trailing slash included, which is a different string and a different answer.
    """
    from lane.git.backend import GitError

    root = context.projects_root
    if root is None:
        return set()
    try:
        return set(context.git.ignored_paths(root / project))
    except GitError:
        # Not fatal: a project that cannot be read has no discovered paths, and the
        # stored answers are still worth listing. `set` then refuses every entry, which
        # is the honest outcome rather than writing against a repository nobody can see.
        return set()


def _in_a_lane(context: Context, project: str) -> set[str]:
    """Paths that are already in at least one open lane of this project.

    Neither screen computes this: `config · preparation` has no lane in hand, and
    entering one knows about that lane only. It is worth reporting because a tick that
    copies a gigabyte and a tick that does nothing have to be tellable apart, and a
    script has no cursor panel to read it from.
    """
    from lane.prepare import present

    lanes = [lane for lane in context.lane_store().list_lanes() if lane.project == project]
    return {
        path
        for path in _discovered(context, project)
        if any(present(lane.path / path) for lane in lanes)
    }


def _commands(context: Context, args: argparse.Namespace) -> int:
    """The `run` steps of one project: the commands screen, named instead of pointed at."""
    from lane.actions import config as screen
    from lane.cli.commands import Unusable, prefilled

    verb = getattr(args, "config_commands_command", None)
    if verb is None:
        raise Unusable("say what to do with the commands: list, add, change, forget")

    if verb == "list":
        return _commands_report(context, args, _a_project(context, args))

    if verb == "add":
        project = _a_project(context, args)
        context.ui = prefilled(context, _command_script(args, project=project), _COMMAND_FLAGS)
        if not screen.add_command(context):
            return cli.EXIT_REFUSED
        return _commands_report(context, args, project)

    step = _a_command(context, args)
    # `forget` asks nothing after the verb, so it is given nothing after the verb: the
    # three fields belong to `change`, and handing them over regardless would be
    # answering questions this path never reaches.
    script: dict[str, object] = {screen.COMMAND_VERB: verb}
    if verb == "change":
        script |= _command_script(args)
    context.ui = prefilled(context, script, _COMMAND_FLAGS)
    if not screen.act_on_command(context, step):
        return cli.EXIT_REFUSED
    return _commands_report(context, args, step.project)


def _command_script(args: argparse.Namespace, *, project: str | None = None) -> dict[str, object]:
    """The three fields, as answers — and `DEFAULT` for every one not given.

    `DEFAULT` is what makes "fields not given keep their stored value" the *screen's*
    behaviour rather than a second one: it takes whatever the prompt itself would have
    defaulted to, and on `change` that is exactly what is stored. Writing the stored
    value out here instead would be this module deciding what "unchanged" means.
    """
    from lane.actions import config as screen
    from lane.actions import picking
    from lane.cli.answers import Prefilled

    script: dict[str, object] = {}
    if project is not None:
        script[picking.PROJECT] = project
    for key, given in (
        (screen.COMMAND, args.run_command),
        (screen.COMMAND_DIRECTORY, args.directory),
        (screen.COMMAND_UNLESS, args.unless),
    ):
        script[key] = given if given is not None else Prefilled.DEFAULT
    return script


def _a_project(context: Context, args: argparse.Namespace) -> str:
    """Which project, refused by name where it is missing or is not one.

    Checked against the projects that are actually there, so a typo is caught before
    anything is written rather than filed under a project nobody has.
    """
    from lane.cli.commands import Unusable
    from lane.projects import list_projects

    named: str | None = getattr(args, "project", None)
    if named is None:
        raise Unusable("say which project: --project <name>")
    known = [project.name for project in list_projects(context.projects_root, context.git)]
    if named not in known:
        raise NotThere(
            f"no project called '{named}'" + (f" — there is {', '.join(known)}" if known else "")
        )
    return named


def _a_command(context: Context, args: argparse.Namespace) -> Step:
    """The step a `<project>/<command>` names.

    The same identifier shape `enter` and `close` use, with **one clause different**: it
    splits on the first slash and takes everything after it verbatim, because a command
    routinely contains a slash (`bin/install`) where a lane name cannot have one.

    A stored command's project is not checked against the projects on disk: forgetting a
    command left behind by a repository that has since gone is exactly what somebody
    would want to do, and refusing it would strand the record.
    """
    from lane.cli.commands import Unusable

    slug: str | None = getattr(args, "command_id", None)
    if not slug:
        raise Unusable(
            "name the command, as <project>/<command> — "
            "'lane config commands list --project <name>' shows them"
        )
    project, separator, command = slug.partition("/")
    if not separator or not project or not command:
        raise Unusable(
            f"'{slug}' is not a command — name one as <project>/<command>, like demo/install"
        )

    for step in context.prepare_store().load().steps:
        if step.verb is Verb.RUN and step.project == project and step.command == command:
            return step
    raise NotThere(
        f"no command called '{slug}' — "
        f"'lane config commands list --project {project}' shows the ones there are"
    )


def _commands_report(context: Context, args: argparse.Namespace, project: str) -> int:
    """This project's run steps after the write, in the order the screen lists them."""
    from lane.actions import config as screen

    found = screen.commands_in(context.prepare_store().load().steps, project)

    if _wants_json(args):
        emit.emit({"project": project, "commands": [_command_json(step) for step in found]})
        return cli.EXIT_OK

    if getattr(args, "config_commands_command", None) == "list":
        for step in found:
            where = step.directory or "the lane root"
            print(f"{step.project}/{step.command} — in {where}")
    return cli.EXIT_OK


def _command_json(step: Step) -> dict[str, object]:
    """One `run` step, with the identifier that names it back.

    `id` is there so a caller can feed a listing straight into `change` or `forget`
    without assembling the slug itself and getting the slash rule wrong.
    """
    return {
        "id": f"{step.project}/{step.command}",
        "project": step.project,
        "command": step.command,
        "directory": step.directory,
        "unless": step.unless,
    }


_COMMAND_FLAGS = {
    "project": "--project",
    "command": "--command",
    "command-directory": "--directory",
    "command-unless": "--unless",
}
"""Which flag would have answered which question, so a refusal can name it."""


def _named(args: argparse.Namespace) -> str:
    """Which setting, refused by name where none was given.

    argparse refuses a *wrong* one in its own wording, which is the consistent one with
    five other subcommands around it. A missing one it cannot refuse — the argument is
    optional so that `--help` is help rather than a complaint — so it is refused here,
    where the refusal can name all three.
    """
    from lane.cli.commands import Unusable

    setting: str | None = getattr(args, "setting", None)
    if setting is None:
        raise Unusable(f"name a setting: {', '.join(SETTINGS)}")
    return setting


def _value(context: Context, key: str) -> str | None:
    """What lane would use for this setting right now, or None where nothing is set.

    None rather than an empty string, because a script has to be able to tell a setting
    nobody has ever given from one set to nothing — and only the first is a real state.
    """
    config = context.config
    if key == "editor":
        return config.editor or None
    path = config.projects_root if key == "projects-root" else config.lanes_root
    return str(path) if path is not None else None


def _report(context: Context, key: str, value: str | None) -> dict[str, object]:
    """The shape `get` and `set` both answer in — the same fields, in the same order.

    One shape for both because they are one question asked twice: `set` is a `get` with
    a write in front of it, and a caller that does `set` then checks the result should
    not have to parse a second schema to do it.
    """
    return {
        "key": key,
        "value": value,
        "overridden_by": context.overridden.get(UNDERSCORED[key]),
    }


def _wants_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


_GROUPS = {
    "get": _get,
    "set": _set,
    "prefixes": _prefixes,
    "preparation": _preparation,
    "commands": _commands,
}
