"""Deferring Ctrl-C across a step that must not be left half-done.

Everywhere else in lane, Ctrl-C stops what is happening: inside a prompt it is
bound and backs out, and during a spinner it becomes `Abandoned`. Both are clean
because every question comes before the first irreversible step, so there is
nothing in flight to leave behind.

Removing a worktree is the exception. It is the one step where stopping half-way is
worse than either finishing or never starting — a partly deleted working copy is a
state nothing in lane knows how to describe, let alone repair. So for the duration
of that step the interrupt is *deferred*: recorded, acknowledged, and raised once
the step is done, at which point stopping costs nothing.

Deferred is not discarded. The user asked to stop and still means it, so leaving the
block raises `KeyboardInterrupt` and the session reports it. And a second Ctrl-C is
never deferred: it means "now", and it is the only way out of a step that turns out
to take far longer than the first one implied.

This pairs with `start_new_session` in the git backend. Without that, the terminal
delivers SIGINT to every process in the foreground group, so git would be killed
mid-removal no matter what the parent decided to do with its own copy of the signal.
"""

from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType


@contextmanager
def deferred(on_interrupt: Callable[[], None]) -> Iterator[None]:
    """Run a step to completion, then raise any Ctrl-C that arrived during it.

    `on_interrupt` is called the moment the first one lands, so the user can see it
    registered — a Ctrl-C that appears to do nothing reads as a hung program, which
    is the very thing deferral is trying not to look like.
    """
    noticed = False

    def handle(signum: int, frame: FrameType | None) -> None:
        nonlocal noticed
        if noticed:
            # The second one means now. The user has been told the step is
            # finishing and has decided not to wait for it.
            signal.default_int_handler(signum, frame)
        noticed = True
        on_interrupt()

    try:
        previous = signal.signal(signal.SIGINT, handle)
    except ValueError:
        # A handler can only be installed from the main thread. Deferring is a
        # nicety; running the step is not, so this is not an error.
        yield
        return

    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)

    # Not reached when the step itself raised: that exception is the more
    # informative one, and it is already on its way.
    if noticed:
        raise KeyboardInterrupt
