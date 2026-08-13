"""The actions table. **The menu is generated from this and nothing else.**

That is the point: the menu cannot drift from what the app can actually do, because
there is no second list to keep in step. The bash version had a table too, but it
also had an argument dispatcher reading it; here the menu is the only consumer.

The menu is always the **full** list. Prerequisites are enforced where they are
used, never by hiding or greying out entries — a user who cannot see an action
cannot find out why it is unavailable, and doctor is what explains that.

`enter` and `close` used to be entries here. They are not hidden: they are the two
verbs the `lanes` screen offers for the row under the cursor. Both began by asking
*which lane* from a picker that showed the same names with none of the status, so
they were worse routes to the same place — and splitting looking from acting is
what made the old listing tiring to use. See ADR 0002.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lane.actions import doctor, list_lanes, open_lane, settings
from lane.context import Context


@dataclass(frozen=True, slots=True)
class Action:
    key: str
    label: str
    description: str
    run: Callable[[Context], None] | None
    """None for `quit`, which the session handles itself."""

    needs_git: bool = True
    """Doctor is the exception: it is the action that explains a missing git."""


ACTIONS: tuple[Action, ...] = (
    Action(
        key="open",
        label="open",
        # Not "a new lane": opening one can also mean picking up a branch that is
        # already there, and this line is exactly the kind of text that outlives what
        # it describes.
        description="New work, or a branch that already exists — your editor opens in it",
        run=open_lane.run,
    ),
    Action(
        key="lanes",
        label="lanes",
        description="Every open lane, where it stands, and what to do with it",
        run=list_lanes.run,
    ),
    Action(
        key="settings",
        label="settings",
        description="Configure lane",
        run=settings.run,
    ),
    Action(
        key="doctor",
        label="doctor",
        description="Check git, gh, the editor and your paths",
        run=doctor.run,
        # Doctor explains missing prerequisites, so it can never sit behind one.
        needs_git=False,
    ),
    Action(
        key="quit",
        label="quit",
        description="Leave lane",
        run=None,
        needs_git=False,
    ),
)


def by_key(key: str) -> Action | None:
    for action in ACTIONS:
        if action.key == key:
            return action
    return None
