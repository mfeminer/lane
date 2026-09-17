"""Doctor: the state of every prerequisite, and which copy of lane is running.

**This action must render its report on a machine where none of what it inspects is
present.** It is the thing that explains a missing prerequisite, so it can never sit
behind one — which is why it never raises and never short-circuits.

It also answers "am I running the copy I just installed", which was a real problem
during development. Under PyInstaller one-file `__file__` points into a temporary
extraction directory that changes every run, so `sys.executable` — the installed
binary — is what gets reported and fingerprinted.

**The checks are data, and printing them is one of two renderings.** `checks()`
decides; `run()` prints; `lane doctor --json` serialises the same tuple. That split
is what stops the machine-readable report becoming a second opinion about the same
machine — the failure mode a hand-written JSON branch would have had, and one nobody
would notice until the two disagreed on a user's laptop.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from lane import __version__, buildinfo
from lane.actions import config as config_screen
from lane.config import ENV_EDITOR, ENV_LANES_ROOT, ENV_PROJECTS_ROOT
from lane.context import Context
from lane.github.gh_client import INSTALL_REMEDY, LOGIN_REMEDY
from lane.prepare import apply
from lane.projects import count_subdirectories, find_nested_repository, list_projects

type Tone = Literal["ok", "warn", "error", "detail"]
"""What one line of the report *is*. `detail` is context, never a verdict."""

type Status = Literal["ok", "warn", "error"]


@dataclass(frozen=True, slots=True)
class Line:
    tone: Tone
    text: str


@dataclass(frozen=True, slots=True)
class Check:
    """One group of the report: what it is called, what it says, and the facts under it.

    A group rather than a single line, because §1 of docs/CONVENTIONS.md makes the
    group the unit — preparation and whether cloning can be free are one group and
    must stay one, with no blank line opening up between them.

    `facts` is what a script reads. The lines are prose and may be reworded; a fact
    is a name and a value, and `--json` promises those are only ever added to.
    """

    name: str
    lines: tuple[Line, ...]
    facts: Mapping[str, object] = field(default_factory=dict)

    @property
    def status(self) -> Status:
        """The worst thing said in the group. `detail` says nothing, so it is `ok`."""
        tones = {line.tone for line in self.lines}
        if "error" in tones:
            return "error"
        if "warn" in tones:
            return "warn"
        return "ok"


def run(context: Context) -> None:
    """Print the report: a heading, then one group per check, then a closing blank."""
    ui = context.ui
    ui.heading("lane doctor")

    tell = {"ok": ui.ok, "warn": ui.warn, "error": ui.error, "detail": ui.detail}
    for check in checks(context):
        ui.blank()
        for line in check.lines:
            tell[line.tone](line.text)
    ui.blank()


def checks(context: Context) -> tuple[Check, ...]:
    """Every check, in the order the report prints them. Never raises."""
    return (
        _running(),
        _git(context),
        _gh(context),
        _config(context),
        _projects(context),
        _lanes(context),
        _preparation(context),
        _editor(context),
    )


def _running() -> Check:
    executable = buildinfo.executable_path()
    build = buildinfo.build_id()
    return Check(
        name="running",
        lines=(
            Line("ok", f"Running: {executable}"),
            Line("detail", f"  lane {__version__}, build {build}"),
            Line("detail", "  If that build is not the one you just installed, an older lane is"),
            Line("detail", "  earlier on your PATH — check with: which -a lane"),
        ),
        facts={"executable": str(executable), "version": __version__, "build": build},
    )


def _git(context: Context) -> Check:
    if context.environment.which("git") is None:
        return Check(
            name="git",
            lines=(
                Line("error", "git is not installed — lane cannot do anything without it."),
                Line("detail", "  Install Xcode command line tools, or: brew install git"),
            ),
            facts={"installed": False, "version": None},
        )
    version = context.environment.tool_version("git", "--version")
    return Check(
        name="git",
        lines=(Line("ok", f"git: {version or 'installed'}"),),
        facts={"installed": True, "version": version},
    )


def _gh(context: Context) -> Check:
    """`gh` is only needed to check a pull request, so its absence is not fatal."""
    if context.environment.which("gh") is None:
        return Check(
            name="gh",
            lines=(
                Line(
                    "warn",
                    "GitHub CLI is not installed — closing a GitHub-backed lane will be refused.",
                ),
                Line("detail", f"  Install it with: {INSTALL_REMEDY}"),
                Line(
                    "detail",
                    "  Everything else, including closing a non-GitHub lane, works without it.",
                ),
            ),
            facts={"installed": False, "logged_in": False, "version": None},
        )

    version = context.environment.tool_version("gh", "--version")
    status = context.environment.tool_version("gh", "auth", "status")
    if status is None:
        return Check(
            name="gh",
            lines=(
                Line("error", f"gh is installed but not logged in — run: {LOGIN_REMEDY}"),
                Line("detail", "  Closing a lane with a GitHub remote will be refused until then."),
            ),
            facts={"installed": True, "logged_in": False, "version": version},
        )
    return Check(
        name="gh",
        lines=(
            Line(
                "ok",
                f"gh: {version or 'installed'} — logged in, pull request state will be checked.",
            ),
        ),
        facts={"installed": True, "logged_in": True, "version": version},
    )


def _config(context: Context) -> Check:
    store = context.config_store
    lines: list[Line] = []
    if store.path.exists():
        lines.append(Line("ok", f"Config: {store.path}"))
    elif store.legacy_path.exists():
        lines.append(Line("warn", f"Config is still in the old shell format: {store.legacy_path}"))
        lines.append(Line("detail", "  It will be migrated to TOML automatically."))
    else:
        lines.append(Line("warn", f"No config yet: {store.path}"))
        lines.append(Line("detail", "  Choose 'config' from the menu to create it."))

    for setting, variable in sorted(context.overridden.items()):
        lines.append(Line("detail", f"  {variable} overrides {setting}"))

    lines.append(Line("detail", f"  State: {context.state_store.path}"))

    return Check(
        name="config",
        lines=tuple(lines),
        facts={
            "path": str(store.path),
            "exists": store.path.exists(),
            "legacy": store.legacy_path.exists(),
            "overrides": dict(sorted(context.overridden.items())),
            "state": str(context.state_store.path),
        },
    )


def _projects(context: Context) -> Check:
    root = context.projects_root
    if root is None:
        return Check(
            name="projects",
            lines=(
                Line(
                    "warn",
                    "Projects folder is not set, so lane does not know where your projects are.",
                ),
                Line("detail", f"  Set it in config, or with {ENV_PROJECTS_ROOT}"),
            ),
            facts={"root": None, "exists": False, "count": None},
        )
    if not root.is_dir():
        return Check(
            name="projects",
            lines=(Line("warn", f"Projects folder is missing: {root}"),),
            facts={"root": str(root), "exists": False, "count": None},
        )

    projects = list_projects(root, context.git)
    if projects:
        return Check(
            name="projects",
            lines=(Line("ok", f"Projects: {root} ({len(projects)} repos)"),),
            facts={"root": str(root), "exists": True, "count": len(projects)},
        )

    lines = [
        Line(
            "warn",
            f"Projects: {root} — none of its {count_subdirectories(root)} "
            "subfolder(s) is a git repository.",
        )
    ]
    nested = find_nested_repository(root, context.git)
    if nested is not None:
        lines.append(Line("detail", f"  Repositories look nested — found one at {nested}"))
        lines.append(Line("detail", f"  Point the projects folder at {nested.parent} instead."))
    return Check(
        name="projects",
        lines=tuple(lines),
        facts={
            "root": str(root),
            "exists": True,
            "count": 0,
            "nested_example": str(nested) if nested is not None else None,
        },
    )


def _lanes(context: Context) -> Check:
    root = context.config.lanes_root
    if root is None:
        return Check(
            name="lanes",
            lines=(
                Line(
                    "warn", f"Lanes folder is not set. Set it in config, or with {ENV_LANES_ROOT}"
                ),
            ),
            facts={"root": None, "exists": False, "open": None},
        )
    if not root.is_dir():
        return Check(
            name="lanes",
            lines=(Line("detail", f"  Lanes folder not created yet: {root}"),),
            facts={"root": str(root), "exists": False, "open": None},
        )
    count = len(context.lane_store().list_lanes())
    return Check(
        name="lanes",
        lines=(Line("ok", f"Lanes: {root} ({count} open)"),),
        facts={"root": str(root), "exists": True, "open": count},
    )


def _preparation(context: Context) -> Check:
    """What preparation is set to do, and whether cloning can actually be free.

    The second half is the one that matters: `cp -c` falls back to a real copy in silence,
    which is exactly why lane calls `clonefile(2)` instead — it fails loudly. This says so
    up front, so nobody discovers it as a gigabyte of missing disk.

    One group, not two: the answers file and whether they can be applied cheaply are
    the same subject, and a blank line between them would say otherwise (§1).
    """
    store = context.prepare_store()
    remembered = store.load()
    lines: list[Line] = []
    facts: dict[str, object] = {"path": str(store.path)}

    if remembered.problem is not None:
        lines.append(Line("error", remembered.problem))
        lines.append(
            Line(
                "detail",
                "  Fix or delete that file; every answer in it will simply be asked again.",
            )
        )
        facts |= {"problem": remembered.problem, "steps": 0, "projects": 0}
    else:
        steps, projects = len(remembered.steps), len(remembered.projects())
        facts |= {"problem": None, "steps": steps, "projects": projects}
        if steps:
            word = "step" if steps == 1 else "steps"
            lines.append(
                Line("ok", f"Preparation: {store.path} ({steps} {word} in {projects} project(s))")
            )
        else:
            lines.append(Line("detail", f"  Preparation: {store.path} — nothing configured yet"))

    projects_root, lanes_root = context.projects_root, context.config.lanes_root
    if projects_root is None or lanes_root is None:
        lines.append(
            Line("detail", "  Copy-on-write could not be checked: set both folders first.")
        )
        facts["copy_on_write"] = None
        return Check(name="preparation", lines=tuple(lines), facts=facts)

    try:
        available = apply.cloning_available(projects_root, lanes_root)
    except OSError as exc:
        # Doctor must render on a machine where nothing it inspects works.
        lines.append(Line("warn", f"Copy-on-write could not be checked: {exc}"))
        facts["copy_on_write"] = None
        return Check(name="preparation", lines=tuple(lines), facts=facts)

    facts["copy_on_write"] = available
    if available:
        lines.append(
            Line(
                "detail",
                f"  Copy-on-write: {projects_root} and {lanes_root} are on one volume that "
                "supports cloning, so bringing a dependency tree into a lane is nearly free.",
            )
        )
    else:
        lines.append(
            Line(
                "warn",
                config_screen.COPY_ON_WRITE_UNAVAILABLE.format(
                    projects=projects_root, lanes=lanes_root
                ),
            )
        )
        lines.append(
            Line(
                "detail", "  Put both roots on one volume, or use 'link' or 'run' for large paths."
            )
        )
    return Check(name="preparation", lines=tuple(lines), facts=facts)


def _editor(context: Context) -> Check:
    editor = context.config.editor
    if not editor:
        return Check(
            name="editor",
            lines=(Line("warn", f"No editor configured. Set one in config, or with {ENV_EDITOR}"),),
            facts={"command": "", "found": False},
        )
    if context.environment.which(editor) is not None:
        return Check(
            name="editor",
            lines=(Line("ok", f"Editor: {editor}"),),
            facts={"command": editor, "found": True},
        )

    app_names = {"cursor": "Cursor", "code": "Visual Studio Code", "zed": "Zed"}
    app = app_names.get(editor)
    if app is not None and context.environment.directory_exists(Path(f"/Applications/{app}.app")):
        return Check(
            name="editor",
            lines=(
                Line(
                    "warn",
                    f"'{editor}' is not on PATH, but {app}.app exists — "
                    f"'open -a {app}' will be used.",
                ),
            ),
            facts={"command": editor, "found": False, "app": app},
        )
    return Check(
        name="editor",
        lines=(
            Line("warn", f"Editor not found: {editor}"),
            Line("detail", "  Lanes will still open; the editor just will not launch."),
        ),
        facts={"command": editor, "found": False},
    )
