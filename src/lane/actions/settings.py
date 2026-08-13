"""Configure lane: three settings, and honesty about the environment.

**First run** (no config file yet) has nothing to show a list of — there is no
"current value" for anything, and lane cannot do anything until all three are set.
So the fixed three-question sequence from before is kept, unchanged, and used only
here.

**Every other run** shows the three settings and their current values as a list —
the same "looking and acting are the same widget" shape as the lanes table
(`list_lanes.py`, ADR 0002). Choosing a row asks that one setting's question and
saves immediately, then returns to the updated list rather than to the menu.

Both paths ask through the same three functions (`_ask_projects_root`,
`_ask_lanes_root`, `_ask_editor`) so validation is defined exactly once.

When an environment variable is currently winning, this still edits the *file* —
but says so plainly, because otherwise saving a value that then appears not to take
effect looks like a bug.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from lane.actions.picking import choose_project
from lane.config import (
    DEFAULT_EDITOR,
    DEFAULT_LANES_DIRNAME,
    ENV_EDITOR,
    ENV_LANES_ROOT,
    ENV_PROJECTS_ROOT,
    Config,
    ConfigStore,
    expand_path,
    home,
)
from lane.context import Context
from lane.prepare import Candidate, Step, Verb, apply
from lane.prepare.sheet import Sheet, inside_from
from lane.projects import count_subdirectories, find_nested_repository, list_projects
from lane.ui.seam import Abandoned, Cell, Choice, Column, Row

BACK = "← Back to the menu"

COLUMNS = (
    Column("setting"),
    Column("current value"),
)

_LABELS = {
    "projects_root": "projects root",
    "lanes_root": "lanes root",
    "editor": "editor",
    "preparation": "preparation",
    "commands": "commands",
}

PREPARATION = "preparation"
"""A row that is a *destination* rather than a setting, so it is a noun (§4).

It leads to one screen covering every project, not to a project list and then a page
each: the lanes table already draws rows from several projects in one table with a dimmed
lead, so this is two levels of nesting instead of three. And that screen is the very one
entering a lane opens — same component, second door.
"""

COMMANDS = "commands"
"""The other half of what `prepare.toml` holds, and the half that is not a checkbox: a
command is typed rather than discovered, and it carries a directory and a guard to edit.
A row of its own rather than a second level under `preparation`, so that `preparation`
can be the shared screen and nothing else."""

PREPARE_BACK = "← Back to settings"
"""Scoped deliberately, as ADR 0002 requires — one step back, not out of settings."""

ADD_COMMAND = "\x00add\x00"

COMMAND_COLUMNS = (
    Column("command"),
    Column("where", drop=1),
)


def run(context: Context) -> None:
    if not context.config_store.path.exists():
        _run_first_time(context)
        return
    _run_list(context)


def _run_first_time(context: Context) -> None:
    """Nothing works until all three are set, so ask in the fixed order and save once."""
    ui = context.ui
    store = context.config_store

    ui.heading("lane settings")
    ui.detail(f"  {store.path}")
    _report_overrides(context)

    ui.blank()
    projects_root = _ask_projects_root(context, None)
    if projects_root is None:
        return

    lanes_root = _ask_lanes_root(context, None, projects_root)
    editor = _ask_editor(context, DEFAULT_EDITOR)

    store.save(replace(Config(), projects_root=projects_root, lanes_root=lanes_root, editor=editor))
    context.reload_config()
    _report_saved(context, store, projects_root=projects_root, lanes_root=lanes_root, editor=editor)


def _run_list(context: Context) -> None:
    """A list you act on, one setting at a time — never a fixed script again."""
    ui = context.ui
    store = context.config_store

    ui.heading("lane settings")
    ui.detail(f"  {store.path}")
    _report_overrides(context)
    ui.blank()

    cursor = 0
    while True:
        current = store.load_file_only()
        rows = _rows(context, current)

        def _rows_now(rows: list[Row[str]] = rows) -> list[Row[str]]:
            return rows

        try:
            key, cursor = ui.browse("lane settings", COLUMNS, _rows_now, back=BACK, cursor=cursor)
        except Abandoned:
            return

        current = store.load_file_only()
        if key == PREPARATION:
            _run_preparation(context)
            continue
        if key == COMMANDS:
            _run_commands(context)
            continue
        if key == "projects_root":
            projects_root = _ask_projects_root(context, current.projects_root)
            if projects_root is None:
                continue
            store.save(replace(current, projects_root=projects_root))
        elif key == "lanes_root":
            base = current.projects_root if current.projects_root is not None else home()
            lanes_root = _ask_lanes_root(context, current.lanes_root, base)
            store.save(replace(current, lanes_root=lanes_root))
        else:
            editor = _ask_editor(context, current.editor or DEFAULT_EDITOR)
            store.save(replace(current, editor=editor))

        context.reload_config()
        ui.blank()
        ui.ok(f"Saved to {store.path}")


_VALUE_LIMIT = 40
"""A path is unbounded and `setting` is not (`"projects root"` is the longest
label there'll ever be), so it's the value that must give way — `table.py` only
ever shrinks the *first* column, and `setting` is first. Without a `short` form
here, a long path pushes the labels themselves into truncation instead."""


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _rows(context: Context, current: Config) -> list[Row[str]]:
    def cell(key: str, text: str) -> Cell:
        variable = context.overridden.get(key)
        suffix = f"  (overridden by {variable})" if variable is not None else ""
        short = _clip(text, _VALUE_LIMIT) + suffix if len(text) > _VALUE_LIMIT else ""
        if variable is not None:
            return Cell(f"{text}{suffix}", tone="warn", short=short)
        return Cell(f"{text}{suffix}", short=short)

    def row(key: str, text: str) -> Row[str]:
        return Row(
            value=key,
            cells=(Cell(_LABELS[key]), cell(key, text)),
            detail=_detail(context, key, text),
        )

    return [
        row("projects_root", _text(current.projects_root)),
        row("lanes_root", _text(current.lanes_root)),
        row("editor", current.editor or DEFAULT_EDITOR),
        row(PREPARATION, _prepared_phrase(context)),
        row(COMMANDS, _commands_phrase(context)),
    ]


def _prepared_phrase(context: Context) -> str:
    """How much is in, the way the other three rows say what they are set to.

    In and out rather than a total, because that *is* the answer this screen holds: a
    count of steps would say how many questions have been asked, not what they said.
    """
    steps = [
        step
        for step in context.prepare_store().load().steps
        if step.verb is not Verb.RUN and step.path
    ]
    if not steps:
        return "nothing yet"
    inside = sum(1 for step in steps if step.verb is Verb.CLONE)
    word = "path" if inside == 1 else "paths"
    return f"{inside} {word} in, {len(steps) - inside} out"


def _commands_phrase(context: Context) -> str:
    commands = [step for step in context.prepare_store().load().steps if step.verb is Verb.RUN]
    if not commands:
        return "nothing yet"
    return f"{len(commands)} step" + ("" if len(commands) == 1 else "s")


def _text(path: Path | None) -> str:
    return str(path) if path is not None else "not set"


def _detail(context: Context, key: str, text: str) -> tuple[str, ...]:
    lines: list[str] = []
    if len(text) > _VALUE_LIMIT:
        # The row's own cell just clipped this — the panel is where the full value
        # lives, same rule as the lanes table's description line.
        lines.append(text)
    variable = context.overridden.get(key)
    if variable is not None:
        lines.append(f"{variable} overrides {_LABELS[key]}.")
        lines.append("Edits below are saved to the file, but the environment still wins.")
    return tuple(lines)


# -- preparation: the same screen entering a lane shows ---------------------------


def _run_preparation(context: Context) -> None:
    """Which ignored paths come into a lane — every project's, on one checklist.

    **The same component `enter` opens**, over the same rows, answered with the same
    keystroke. Not a screen that resembles it: resemblance drifts, and this one had
    already drifted into a table you pressed `Enter` on, chose *change* in, and then
    picked a verb from — three screens to move one path.

    There is no lane here, so there is no `in lane` column and nothing is applied: the
    answers are written, and the next enter of any lane in that project acts on them.
    """
    ui = context.ui
    store = context.prepare_store()

    ui.heading("lane settings · preparation")
    ui.detail(f"  {store.path}")
    remembered = store.load()
    if remembered.problem is not None:
        ui.warn(remembered.problem)

    paths = tuple(step for step in remembered.steps if step.verb is not Verb.RUN and step.path)
    if not paths:
        # §12: a screen built around a list draws no frame over an empty one, and a
        # checklist has no action row to keep it alive — every row it has is a path.
        ui.blank()
        ui.detail("Nothing has been answered yet. Entering a lane is what asks.")
        return

    sheet = Sheet(
        _candidates(paths),
        source=lambda one: _source_of(context, one),
        inside=inside_from(paths),
        lead=True,
    )

    ui.blank()
    try:
        chosen = ui.check(
            _prepared_title(paths),
            sheet.columns,
            sheet.rows,
            checked=sheet.checked,
            summary=sheet.summary,
            fill=sheet.fill,
        )
    except Abandoned:
        return

    answered = sheet.steps(chosen)
    # One write, not one per path: `add` reloads and rewrites the file each time, which
    # over fifty rows is fifty read-modify-write cycles and fifty chances to be
    # interrupted half way through the set the user just accepted.
    keys = {step.key for step in answered}
    store.save([*(step for step in remembered.steps if step.key not in keys), *answered])
    _report_preparation(context, remembered.steps, answered)


def _candidates(steps: Sequence[Step]) -> list[Candidate]:
    """Ordered by project, then path — and never rearranged while on screen."""
    ordered = sorted(steps, key=lambda step: (step.project.lower(), step.path.lower()))
    return [Candidate(path=step.path, project=step.project) for step in ordered]


def _source_of(context: Context, candidate: Candidate) -> Path:
    root = context.projects_root
    if root is None:
        return Path("/nonexistent") / candidate.path
    return root / candidate.project / candidate.path


def _prepared_title(steps: Sequence[Step]) -> str:
    """Answers "what am I looking at" rather than repeating the screen's own name (§1)."""
    count = len(steps)
    word = "path" if count == 1 else "paths"
    projects = len({step.project for step in steps})
    project_word = "project" if projects == 1 else "projects"
    return f"{count} answered {word} in {projects} {project_word}"


def _report_preparation(context: Context, before: Sequence[Step], answered: Sequence[Step]) -> None:
    """Say what changed, and say the thing that changes a decision where it was made."""
    ui = context.ui
    was = {(step.project, step.path): step.verb for step in before}
    changed = [step for step in answered if was.get((step.project, step.path)) is not step.verb]

    ui.blank()
    if not changed:
        ui.ok("Nothing changed.")
        return

    brought_in = [step for step in changed if step.verb is Verb.CLONE]
    if brought_in:
        _warn_about_cloning(context)
    for step in changed:
        state = "in" if step.verb is Verb.CLONE else "out"
        ui.ok(f"{step.project}/{step.path} — {state}")


# -- preparation: the commands, which are not paths -------------------------------


def _run_commands(context: Context) -> None:
    """A `run` step is typed rather than discovered, and carries a directory and a guard.

    None of that is a checkbox, so this stays the list you act on a row of — the settings
    list's own shape, and the lanes table's. It is a second row rather than a second level
    under `preparation` because the two are different kinds of thing, and folding a typed
    command into a screen of discovered paths would be the resemblance this change exists
    to remove.
    """
    ui = context.ui
    store = context.prepare_store()

    ui.heading("lane settings · commands")
    ui.detail(f"  {store.path}")
    ui.blank()

    cursor = 0
    while True:
        rows = _command_rows(store.load().steps)

        def _rows_now(rows: list[Row[Step | str]] = rows) -> list[Row[Step | str]]:
            return rows

        try:
            chosen, cursor = ui.browse(
                "commands", COMMAND_COLUMNS, _rows_now, back=PREPARE_BACK, cursor=cursor
            )
        except Abandoned:
            return

        if chosen == ADD_COMMAND:
            _add_command(context)
            continue
        assert isinstance(chosen, Step)
        _act_on_command(context, chosen)


def _command_rows(steps: Sequence[Step]) -> list[Row[Step | str]]:
    """Ordered by project, then command — and never rearranged while on screen."""
    ordered = sorted(
        (step for step in steps if step.verb is Verb.RUN),
        key=lambda step: (step.project.lower(), step.command.lower()),
    )
    rows: list[Row[Step | str]] = [
        Row(
            value=step,
            cells=(
                Cell(step.command, lead=f"{step.project}/"),
                Cell(step.directory or "the lane root", tone="dim"),
            ),
            detail=_command_detail(step),
        )
        for step in ordered
    ]
    # An action row, like the visible way back: a screen whose only purpose is to let you
    # add the first command cannot answer an empty list with a line of prose (§12).
    rows.append(Row(value=ADD_COMMAND, cells=(Cell("add a command"), Cell(""))))
    return rows


def _command_detail(step: Step) -> tuple[str, ...]:
    if step.unless:
        return (f"Skipped when {step.unless} is already in the lane.",)
    return ("Runs on every enter — nothing guards it.",)


def _act_on_command(context: Context, step: Step) -> None:
    """Two verbs for the row under the cursor, exactly as the lanes table offers two."""
    try:
        verb = context.ui.choose(
            f"{step.project}/{step.command}",
            [
                Choice("change", "change", "edit the command, where it runs, or its guard"),
                Choice("forget", "forget", "and stop running it"),
            ],
        )
    except Abandoned:
        return

    if verb == "forget":
        context.prepare_store().forget(step)
        context.ui.ok(f"Forgot {step.project}/{step.command}.")
        return

    command = context.ui.text("Command to run", default=step.command)
    directory = context.ui.text("Where to run it, relative to the lane", default=step.directory)
    unless = context.ui.text("Skip it when this path is already in the lane", default=step.unless)
    context.prepare_store().forget(step)
    _save_command(context, step.project, command, directory, unless)


def _add_command(context: Context) -> None:
    project = choose_project(context, "Which project?")
    if project is None:
        return
    command = context.ui.text("Command to run")
    directory = context.ui.text("Where to run it, relative to the lane")
    unless = context.ui.text("Skip it when this path is already in the lane")
    _save_command(context, project.name, command, directory, unless)


def _save_command(
    context: Context, project: str, command: str, directory: str, unless: str
) -> None:
    if not command.strip():
        context.ui.error("A command is required.")
        return
    context.prepare_store().add(
        Step(
            project=project,
            verb=Verb.RUN,
            command=command.strip(),
            directory=directory.strip().strip("/"),
            unless=unless.strip().strip("/"),
        )
    )
    if not unless.strip():
        context.ui.warn(
            "Nothing guards this, so it runs on every enter — and entering is instant today."
        )
    context.ui.ok(f"{project}/{command.strip()} — run")


def _warn_about_cloning(context: Context) -> None:
    """Say the thing that changes the decision, where the decision is being made.

    doctor reports the copy-on-write question too, but nobody consults doctor before
    configuring something they expect to be free — so it is said in the same words here.
    """
    projects_root, lanes_root = context.projects_root, context.config.lanes_root
    if projects_root is None or lanes_root is None:
        return
    if apply.cloning_available(projects_root, lanes_root):
        return
    context.ui.warn(COPY_ON_WRITE_UNAVAILABLE.format(projects=projects_root, lanes=lanes_root))
    context.ui.detail("  Put both roots on one volume, or leave the large paths out.")


COPY_ON_WRITE_UNAVAILABLE = (
    "Copy-on-write is not available: {projects} and {lanes} are on different volumes, "
    "so bringing a path in is a real copy — slow, and it uses real disk."
)
"""One sentence, shared by doctor and by settings, so they cannot say it differently."""


def _report_overrides(context: Context) -> None:
    ui = context.ui
    if not context.overridden:
        return
    ui.blank()
    ui.warn("The environment is currently winning over this file:")
    for setting, variable in sorted(context.overridden.items()):
        ui.detail(f"  {variable} overrides {setting}")
    ui.detail("  Edits below are saved to the file, but the environment still wins.")


def _report_saved(
    context: Context,
    store: ConfigStore,
    *,
    projects_root: Path,
    lanes_root: Path,
    editor: str,
) -> None:
    ui = context.ui
    ui.blank()
    ui.ok(f"Saved to {store.path}")
    ui.info(f"  Projects : {projects_root}")
    ui.info(f"  Lanes    : {lanes_root}")
    ui.info(f"  Editor   : {editor}")

    if _env_note(context):
        ui.blank()
        ui.detail("Remember: the environment variables listed above still take precedence.")


def _ask_projects_root(context: Context, current: Path | None) -> Path | None:
    """Everything depends on this being right, so a folder with no projects is refused."""
    ui = context.ui
    ui.detail("One git repository per subfolder is expected: <folder>/<project>/.git")

    while True:
        typed = ui.text("Which folder do your projects sit in", default=str(current or ""))
        if not typed.strip():
            ui.error("A path is required.")
            continue

        candidate = expand_path(typed)
        if not candidate.is_dir():
            ui.error(f"No such directory: {candidate}")
            continue

        projects = list_projects(candidate, context.git)
        if not projects:
            ui.error(
                f"No projects in {candidate} — none of its "
                f"{count_subdirectories(candidate)} subfolder(s) is a git repository."
            )
            ui.detail(f"  Expected {candidate}/<project>/.git")
            nested = find_nested_repository(candidate, context.git)
            if nested is not None:
                ui.detail(f"  Your repositories look nested — found one at {nested}")
                ui.detail(f"  Try {nested.parent} instead.")
            continue

        ui.ok(f"Found {len(projects)} project(s) to open lanes in.")
        return candidate


def _ask_lanes_root(context: Context, current: Path | None, projects_root: Path) -> Path:
    """Offer somewhere sensible, but let the user park lanes wherever they like.

    The suggestion sits **beside** the projects folder — `/x/y/projects` implies
    `/x/y/Lanes` — because that is what someone who has just named their projects
    folder is going to type. It deliberately does not sit *inside* it: lane warns
    about that, since the repositories would start showing up as lanes.

    An already-configured folder always wins over the suggestion. A choice the user
    has made is never quietly replaced by a guess.
    """
    ui = context.ui
    suggestion = current if current is not None else _beside(projects_root)

    typed = ui.text("Where should lanes be parked", default=str(suggestion))
    lanes_root = expand_path(typed) if typed.strip() else suggestion

    if lanes_root == projects_root or projects_root in lanes_root.parents:
        ui.warn("That sits inside your projects folder — your repos may show up as lanes.")
    return lanes_root


def _beside(projects_root: Path) -> Path:
    """`/x/y/projects` -> `/x/y/Lanes`, falling back to the home directory."""
    parent = projects_root.parent
    if parent == projects_root or str(parent) in {"", "/"}:
        # A projects root at the filesystem root; putting lanes in / would be rude.
        return home() / DEFAULT_LANES_DIRNAME
    return parent / DEFAULT_LANES_DIRNAME


def _ask_editor(context: Context, current: str) -> str:
    ui = context.ui
    editor = ui.text("Editor command to open a lane with", default=current)

    if context.environment.which(editor) is not None:
        ui.ok(f"'{editor}' found.")
        return editor

    # A macOS editor can be installed as an .app without its shell command.
    app_names = {"cursor": "Cursor", "code": "Visual Studio Code", "zed": "Zed"}
    app = app_names.get(editor)
    if app is not None and context.environment.directory_exists(Path(f"/Applications/{app}.app")):
        ui.ok(f"{app}.app found — 'open -a {app}' will be used.")
        if editor == "cursor":
            ui.detail("  Tip: Cursor > Cmd+Shift+P > \"Shell Command: Install 'cursor' command\"")
        return editor

    ui.warn(f"'{editor}' is not on your PATH — lanes will open, but the editor will not launch.")
    return editor


def _env_note(context: Context) -> bool:
    return any(
        variable in context.overridden.values()
        for variable in (ENV_PROJECTS_ROOT, ENV_LANES_ROOT, ENV_EDITOR)
    )
