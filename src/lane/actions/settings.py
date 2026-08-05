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

from dataclasses import replace
from pathlib import Path

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
from lane.projects import count_subdirectories, find_nested_repository, list_projects
from lane.ui.seam import Abandoned, Cell, Column, Row

BACK = "← Back to the menu"

COLUMNS = (
    Column("setting"),
    Column("current value"),
)

_LABELS = {
    "projects_root": "projects root",
    "lanes_root": "lanes root",
    "editor": "editor",
}


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
    ]


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
