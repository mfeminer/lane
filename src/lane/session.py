"""The menu loop.

Choose an action, run it, come back to the menu. The session ends when you quit.

This is where `Abandoned` is caught. Because every question an action asks comes
before its first irreversible step, catching it here and looping is all the
"rollback" lane needs — and the only kind that cannot be got wrong.
"""

from __future__ import annotations

from lane import __version__
from lane.actions import ACTIONS, Action
from lane.context import Context
from lane.errors import LaneError
from lane.git.backend import GitError
from lane.ui.seam import Abandoned, Choice

EXIT_OK = 0


def run(context: Context, *, git_available: bool = True) -> int:
    ui = context.ui

    ui.heading(f"lane {__version__}")
    if not git_available:
        # The session still starts, and doctor still works: it is the action that
        # explains this. Everything else refuses.
        ui.error("git is not installed, so lane cannot manage worktrees.")
        ui.detail("  Choose 'doctor' for the details, or install git and start again.")

    while True:
        try:
            action = _choose_action(context)
        except Abandoned:
            # q, Esc or Ctrl-C at the menu ends the session cleanly.
            return EXIT_OK

        if action is None or action.run is None:
            return EXIT_OK

        if action.needs_git and not git_available:
            ui.blank()
            ui.error(f"'{action.label}' needs git, which is not installed.")
            ui.detail("  Choose 'doctor' for the details.")
            continue

        _run_action(context, action)


def _choose_action(context: Context) -> Action | None:
    """The menu, rendered from the actions table and nothing else."""
    options = [
        Choice(label=action.label, value=action, hint=action.description) for action in ACTIONS
    ]
    # No title: the session heading above already names lane and its version, and
    # repeating it put a second bare "lane" on screen. No Back entry either: `quit`
    # is the way out of the menu, and two of them would be one too many.
    return context.ui.choose("", options, back=None)


def _run_action(context: Context, action: Action) -> None:
    ui = context.ui
    assert action.run is not None
    try:
        action.run(context)
    except Abandoned:
        # Backing out is a clean no-op by construction, so there is nothing to
        # report: every other tool simply shows the menu again. "Left as it was."
        # explained nothing to anyone who had not read the source.
        pass
    except LaneError as exc:
        ui.error(str(exc))
    except GitError as exc:
        ui.error(f"git could not do that: {exc}")
    except OSError as exc:
        ui.error(f"Something on disk got in the way: {exc}")
    ui.blank()
