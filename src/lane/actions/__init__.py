"""The actions table. **The menu is generated from this and nothing else.**

That is the point: the menu cannot drift from what the app can actually do, because
there is no second list to keep in step. The bash version had a table too, but it
also had an argument dispatcher reading it; here the menu is the only consumer.

The menu is always the **full** list. Prerequisites are enforced where they are
used, never by hiding or greying out entries — a user who cannot see an action
cannot find out why it is unavailable, and doctor is what explains that.

The listing's entry is `list`, and it is the same word the subcommand uses. §4 of
docs/CONVENTIONS.md prefers a noun for a destination, which `lanes` was — but one
concept with two names is the worse fault of the two (§14), and the subcommand has to
be `list` because that is what every tool in this space calls it. AGENTS.md carries
the argument. `open` was already a verb-shaped way into a destination.

`enter` and `close` used to be entries here. They are not hidden: they are the two
verbs the `lanes` screen offers for the row under the cursor. Both began by asking
*which lane* from a picker that showed the same names with none of the status, so
they were worse routes to the same place — and splitting looking from acting is
what made the old listing tiring to use. See ADR 0002.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lane.actions import config, doctor, list_lanes, open_lane
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
        key="list",
        label="list",
        description="Every open lane, where it stands, and what to do with it",
        run=list_lanes.run,
    ),
    Action(
        key="config",
        label="config",
        description="Configure lane",
        run=config.run,
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
