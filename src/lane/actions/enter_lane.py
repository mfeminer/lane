"""Relaunch the editor in a lane you already have open.

Not a menu entry any more: you enter a lane from the listing, with the cursor on
it, because "which lane?" is a question the listing answers better than a bare
picker does (ADR 0002). What is left here is the launch itself, in one place, so
the missing-editor warning is worded the same wherever it comes from.

The bash version's `where`, which printed a path so `cd "$(lane where)"` could move
the caller's shell, is deliberately gone: the editor's integrated terminal is
already inside the worktree, so the workflow never needs it.
"""

from __future__ import annotations

from lane.context import Context
from lane.lanes import Lane


def enter(context: Context, lane: Lane) -> None:
    launch = context.environment.launch_editor(context.config.editor, lane.path)
    if launch.launched:
        context.ui.ok(launch.detail)
    else:
        context.ui.warn(f"{launch.detail} — open it yourself: {lane.path}")
        context.ui.detail("  Change the editor command in settings.")
