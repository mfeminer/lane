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

from lane import cli
from lane.cli import emit
from lane.cli.commands import NotThere
from lane.cli.parser import SETTINGS
from lane.context import Context

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


_GROUPS = {"get": _get, "set": _set, "prefixes": _prefixes}
