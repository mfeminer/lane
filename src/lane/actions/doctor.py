"""Doctor: the state of every prerequisite, and which copy of lane is running.

**This action must render its report on a machine where none of what it inspects is
present.** It is the thing that explains a missing prerequisite, so it can never sit
behind one — which is why it never raises and never short-circuits.

It also answers "am I running the copy I just installed", which was a real problem
during development. Under PyInstaller one-file `__file__` points into a temporary
extraction directory that changes every run, so `sys.executable` — the installed
binary — is what gets reported and fingerprinted.
"""

from __future__ import annotations

from pathlib import Path

from lane import __version__, buildinfo
from lane.actions import settings
from lane.config import ENV_EDITOR, ENV_LANES_ROOT, ENV_PROJECTS_ROOT
from lane.context import Context
from lane.github.gh_client import INSTALL_REMEDY, LOGIN_REMEDY
from lane.prepare import apply
from lane.projects import count_subdirectories, find_nested_repository, list_projects


def run(context: Context) -> None:
    ui = context.ui

    ui.heading("lane doctor")

    # -- which copy is running -----------------------------------------------
    ui.blank()
    ui.ok(f"Running: {buildinfo.executable_path()}")
    ui.detail(f"  lane {__version__}, build {buildinfo.build_id()}")
    ui.detail("  If that build is not the one you just installed, an older lane is")
    ui.detail("  earlier on your PATH — check with: which -a lane")

    # -- tools ---------------------------------------------------------------
    # Each check is its own group (docs/CONVENTIONS.md §1): a blank line between
    # every one, none within.
    ui.blank()
    _report_git(context)
    ui.blank()
    _report_gh(context)

    # -- configuration -------------------------------------------------------
    ui.blank()
    _report_config(context)
    ui.blank()
    _report_projects(context)
    ui.blank()
    _report_lanes(context)
    ui.blank()
    _report_preparation(context)
    ui.blank()
    _report_editor(context)
    ui.blank()


def _report_git(context: Context) -> None:
    ui = context.ui
    if context.environment.which("git") is None:
        ui.error("git is not installed — lane cannot do anything without it.")
        ui.detail("  Install Xcode command line tools, or: brew install git")
        return
    version = context.environment.tool_version("git", "--version")
    ui.ok(f"git: {version or 'installed'}")


def _report_gh(context: Context) -> None:
    """`gh` is only needed to check a pull request, so its absence is not fatal."""
    ui = context.ui
    if context.environment.which("gh") is None:
        ui.warn("GitHub CLI is not installed — closing a GitHub-backed lane will be refused.")
        ui.detail(f"  Install it with: {INSTALL_REMEDY}")
        ui.detail("  Everything else, including closing a non-GitHub lane, works without it.")
        return

    version = context.environment.tool_version("gh", "--version")
    status = context.environment.tool_version("gh", "auth", "status")
    if status is None:
        ui.error(f"gh is installed but not logged in — run: {LOGIN_REMEDY}")
        ui.detail("  Closing a lane with a GitHub remote will be refused until then.")
        return
    ui.ok(f"gh: {version or 'installed'} — logged in, pull request state will be checked.")


def _report_config(context: Context) -> None:
    ui = context.ui
    store = context.config_store
    if store.path.exists():
        ui.ok(f"Config: {store.path}")
    elif store.legacy_path.exists():
        ui.warn(f"Config is still in the old shell format: {store.legacy_path}")
        ui.detail("  It will be migrated to TOML automatically.")
    else:
        ui.warn(f"No config yet: {store.path}")
        ui.detail("  Choose 'settings' from the menu to create it.")

    if context.overridden:
        for setting, variable in sorted(context.overridden.items()):
            ui.detail(f"  {variable} overrides {setting}")

    ui.detail(f"  State: {context.state_store.path}")


def _report_projects(context: Context) -> None:
    ui = context.ui
    root = context.projects_root
    if root is None:
        ui.warn("Projects folder is not set, so lane does not know where your projects are.")
        ui.detail(f"  Set it in settings, or with {ENV_PROJECTS_ROOT}")
        return
    if not root.is_dir():
        ui.warn(f"Projects folder is missing: {root}")
        return

    projects = list_projects(root, context.git)
    if projects:
        ui.ok(f"Projects: {root} ({len(projects)} repos)")
        return

    ui.warn(
        f"Projects: {root} — none of its {count_subdirectories(root)} "
        "subfolder(s) is a git repository."
    )
    nested = find_nested_repository(root, context.git)
    if nested is not None:
        ui.detail(f"  Repositories look nested — found one at {nested}")
        ui.detail(f"  Point the projects folder at {nested.parent} instead.")


def _report_lanes(context: Context) -> None:
    ui = context.ui
    root = context.config.lanes_root
    if root is None:
        ui.warn(f"Lanes folder is not set. Set it in settings, or with {ENV_LANES_ROOT}")
        return
    if not root.is_dir():
        ui.detail(f"  Lanes folder not created yet: {root}")
        return
    count = len(context.lane_store().list_lanes())
    ui.ok(f"Lanes: {root} ({count} open)")


def _report_preparation(context: Context) -> None:
    """What preparation is set to do, and whether cloning can actually be free.

    The second half is the one that matters: `cp -c` falls back to a real copy in silence,
    which is exactly why lane calls `clonefile(2)` instead — it fails loudly. This says so
    up front, so nobody discovers it as a gigabyte of missing disk.
    """
    ui = context.ui
    store = context.prepare_store()
    remembered = store.load()

    if remembered.problem is not None:
        ui.error(remembered.problem)
        ui.detail("  Fix or delete that file; every answer in it will simply be asked again.")
    else:
        steps, projects = len(remembered.steps), len(remembered.projects())
        if steps:
            word = "step" if steps == 1 else "steps"
            ui.ok(f"Preparation: {store.path} ({steps} {word} in {projects} project(s))")
        else:
            ui.detail(f"  Preparation: {store.path} — nothing configured yet")

    projects_root, lanes_root = context.projects_root, context.config.lanes_root
    if projects_root is None or lanes_root is None:
        ui.detail("  Copy-on-write could not be checked: set both folders first.")
        return

    try:
        available = apply.cloning_available(projects_root, lanes_root)
    except OSError as exc:
        # Doctor must render on a machine where nothing it inspects works.
        ui.warn(f"Copy-on-write could not be checked: {exc}")
        return

    if available:
        ui.detail(
            f"  Copy-on-write: {projects_root} and {lanes_root} are on one volume that "
            "supports cloning, so bringing a dependency tree into a lane is nearly free."
        )
        return
    ui.warn(settings.COPY_ON_WRITE_UNAVAILABLE.format(projects=projects_root, lanes=lanes_root))
    ui.detail("  Put both roots on one volume, or use 'link' or 'run' for large paths.")


def _report_editor(context: Context) -> None:
    ui = context.ui
    editor = context.config.editor
    if not editor:
        ui.warn(f"No editor configured. Set one in settings, or with {ENV_EDITOR}")
        return
    if context.environment.which(editor) is not None:
        ui.ok(f"Editor: {editor}")
        return

    app_names = {"cursor": "Cursor", "code": "Visual Studio Code", "zed": "Zed"}
    app = app_names.get(editor)
    if app is not None and context.environment.directory_exists(Path(f"/Applications/{app}.app")):
        ui.warn(f"'{editor}' is not on PATH, but {app}.app exists — 'open -a {app}' will be used.")
        return
    ui.warn(f"Editor not found: {editor}")
    ui.detail("  Lanes will still open; the editor just will not launch.")
