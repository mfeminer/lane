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

from collections.abc import Callable, Sequence
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
from lane.prepare import Step, Verb, apply
from lane.projects import count_subdirectories, find_nested_repository, list_projects
from lane.ui.seam import Abandoned, Cell, Choice, Column, Fill, Row

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
}

PREPARATION = "preparation"
"""A row that is a *destination* rather than a setting, so it is a noun (§4).

It leads to one screen listing every project's steps, not to a project list and then a
page each: the lanes table already draws rows from several projects in one table with a
dimmed lead, so this is two levels of nesting instead of three.
"""

PREPARE_BACK = "← Back to settings"
"""Scoped deliberately, as ADR 0002 requires — one step back, not out of settings."""

ADD_STEP = "\x00add\x00"

PREPARE_COLUMNS = (
    Column("path"),
    # Informs the decision `verb` records; it does not answer the screen's question, so it
    # is the one that goes when the terminal is narrow. Same order as the per-enter screen:
    # two screens showing the same concept do not shuffle their columns.
    Column("size", drop=1),
    Column("verb"),
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
    ]


def _prepared_phrase(context: Context) -> str:
    """How much is there, the way the other three rows say what they are set to."""
    remembered = context.prepare_store().load()
    steps, projects = len(remembered.steps), len(remembered.projects())
    if not steps:
        return "nothing yet"
    step_word = "step" if steps == 1 else "steps"
    project_word = "project" if projects == 1 else "projects"
    return f"{steps} {step_word} in {projects} {project_word}"


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


# -- preparation ------------------------------------------------------------------


def _run_preparation(context: Context) -> None:
    """Every project's steps, in one table you act on one row at a time.

    The same shape as the settings list itself and the lanes table, and for the same
    reason: looking and acting are the same widget. The project is a dimmed lead on the
    subject, exactly as the listing does when lanes span projects — which is what makes
    a second level of nesting unnecessary.

    This is where a decision made months ago is changed, which is the whole reason the
    per-enter screen can remember every answer without a "remember this?" column: the
    remedy for a wrong answer is one row here.
    """
    ui = context.ui
    store = context.prepare_store()

    ui.heading("lane settings · preparation")
    ui.detail(f"  {store.path}")
    remembered = store.load()
    if remembered.problem is not None:
        ui.warn(remembered.problem)
    ui.blank()

    cursor = 0
    while True:
        rows = _prepare_rows(store.load().steps)

        def _rows_now(rows: list[Row[Step | str]] = rows) -> list[Row[Step | str]]:
            return rows

        try:
            chosen, cursor = ui.browse(
                "preparation",
                PREPARE_COLUMNS,
                _rows_now,
                back=PREPARE_BACK,
                fill=_measure_into(context, rows),
                cursor=cursor,
            )
        except Abandoned:
            return

        if chosen == ADD_STEP:
            _add_step(context)
            continue
        assert isinstance(chosen, Step)
        _act_on_step(context, chosen)


def _prepare_rows(steps: Sequence[Step]) -> list[Row[Step | str]]:
    """Ordered by project, then subject — and never rearranged while on screen."""
    ordered = sorted(steps, key=lambda step: (step.project.lower(), step.subject.lower()))
    rows: list[Row[Step | str]] = [
        Row(
            value=step,
            cells=(
                Cell(step.subject, lead=f"{step.project}/"),
                _MEASURING if step.verb is not Verb.RUN else Cell("—", tone="dim"),
                Cell(step.describe(), tone="dim" if step.verb is Verb.SKIP else ""),
            ),
            detail=_step_detail(step),
        )
        for step in ordered
    ]
    # An action row, like the visible way back: a screen whose only purpose is to let you
    # add the first step cannot answer an empty list with a line of prose (§12).
    rows.append(Row(value=ADD_STEP, cells=(Cell("add a step"), Cell(""), Cell(""))))
    return rows


_MEASURING = Cell("measuring…", tone="dim")


def _step_detail(step: Step) -> tuple[str, ...]:
    lines = [f"{step.project}: {step.subject}"]
    if step.verb is Verb.RUN and step.unless:
        lines.append(f"Skipped when {step.unless} is already in the lane.")
    elif step.verb is Verb.RUN:
        lines.append("Runs on every enter — nothing guards it.")
    elif step.verb is Verb.CLONE and step.refresh:
        lines.append("Replaced on every enter, including anything the lane changed.")
    elif step.verb is Verb.LINK:
        lines.append("A symlink: always current, and the lane writes into the main clone.")
    return tuple(lines)


def _measure_into(context: Context, rows: list[Row[Step | str]]) -> Fill:
    """Sizes behind the screen, the lanes table's own shape and its own `fill`.

    A step configured months ago is worth re-measuring before it is changed, and `du` on
    a large tree is too slow to hold up the first paint.
    """
    root = context.projects_root

    def fill(notify: Callable[[], None]) -> None:
        if root is None:
            return
        for index, row in enumerate(rows):
            step = row.value
            if not isinstance(step, Step) or step.verb is Verb.RUN:
                continue
            size = apply.measure(root / step.project / step.path)
            rows[index] = replace(
                row,
                cells=(row.cells[0], Cell(apply.size_phrase(size), tone="dim"), row.cells[2]),
            )
            notify()

    return fill


def _act_on_step(context: Context, step: Step) -> None:
    """Two verbs for the row under the cursor, exactly as the lanes table offers two."""
    try:
        verb = context.ui.choose(
            f"{step.project}/{step.subject}",
            [
                Choice("change", "change", "answer this one differently"),
                Choice("forget", "forget", "and be asked about it again"),
            ],
        )
    except Abandoned:
        return

    if verb == "forget":
        context.prepare_store().forget(step)
        context.ui.ok(f"Forgot {step.project}/{step.subject} — it will be asked about again.")
        return

    if step.verb is Verb.RUN:
        _change_command(context, step)
        return
    _change_path_verb(context, step)


def _change_path_verb(context: Context, step: Step) -> None:
    """The one place `refresh` can be set — see `prepare.Step.refresh` for why."""
    chosen = context.ui.choose(
        f"What should lane do with {step.subject}",
        [
            Choice("skip", (Verb.SKIP, False), "leave it out of the lane"),
            Choice("clone", (Verb.CLONE, False), "copy it in when it is missing"),
            Choice(
                "clone, refreshed",
                (Verb.CLONE, True),
                "replace it on every enter, including what the lane changed",
            ),
            Choice("link", (Verb.LINK, False), "a symlink to the main clone"),
        ],
    )
    verb, refresh = chosen
    context.prepare_store().add(replace(step, verb=verb, refresh=refresh))
    _warn_about_verb(context, verb)
    context.ui.ok(f"{step.project}/{step.subject} — {verb}")


def _change_command(context: Context, step: Step) -> None:
    command = context.ui.text("Command to run", default=step.command)
    directory = context.ui.text("Where to run it, relative to the lane", default=step.directory)
    unless = context.ui.text("Skip it when this path is already in the lane", default=step.unless)
    _save_command(context, step.project, command, directory, unless)


def _add_step(context: Context) -> None:
    """A `run` step exists only here: the per-enter screen is one row per *discovered*
    path, and a command is not one."""
    project = choose_project(context, "Which project?")
    if project is None:
        return

    verb = context.ui.choose(
        f"What should lane do in {project.name}",
        [
            Choice("clone", Verb.CLONE, "copy an ignored path in from the main clone"),
            Choice("link", Verb.LINK, "symlink an ignored path to the main clone"),
            Choice("run", Verb.RUN, "run a command in the lane"),
            Choice("skip", Verb.SKIP, "never bring a path in, and stop being asked"),
        ],
    )

    if verb is Verb.RUN:
        command = context.ui.text("Command to run")
        directory = context.ui.text("Where to run it, relative to the lane")
        unless = context.ui.text("Skip it when this path is already in the lane")
        _save_command(context, project.name, command, directory, unless)
        return

    path = context.ui.text("Which path, relative to the repository root")
    if not path.strip():
        context.ui.error("A path is required.")
        return
    context.prepare_store().add(Step(project=project.name, verb=verb, path=path.strip().strip("/")))
    _warn_about_verb(context, verb)
    context.ui.ok(f"{project.name}/{path.strip()} — {verb}")


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


def _warn_about_verb(context: Context, verb: Verb) -> None:
    """Say the thing that changes the decision, where the decision is being made.

    doctor reports the copy-on-write question too, but nobody consults doctor before
    configuring something they expect to be free — so it is said in the same words here.
    """
    ui = context.ui
    if verb is Verb.LINK:
        ui.warn("A symlink is always current, and anything the lane writes there goes into")
        ui.detail("  the main clone. Use 'clone' for a path the lane will modify.")
        return
    if verb is not Verb.CLONE:
        return
    projects_root, lanes_root = context.projects_root, context.config.lanes_root
    if projects_root is None or lanes_root is None:
        return
    if not apply.cloning_available(projects_root, lanes_root):
        ui.warn(COPY_ON_WRITE_UNAVAILABLE.format(projects=projects_root, lanes=lanes_root))
        ui.detail("  Put both roots on one volume, or use 'link' or 'run' for large paths.")


COPY_ON_WRITE_UNAVAILABLE = (
    "Copy-on-write is not available: {projects} and {lanes} are on different volumes, "
    "so a 'clone' step is a real copy — slow, and it uses real disk."
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
