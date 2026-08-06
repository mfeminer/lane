"""Ctrl-C across a step that must not be left half-done.

Real signals, sent to this process. There is no other honest way to test this: the
whole behaviour is what the interpreter does with SIGINT.
"""

from __future__ import annotations

import os
import signal
import threading
import time

import pytest

from lane import interrupts

TIMEOUT = 2.0


def _interrupt_self() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def _settle(reached: list[str], count: int = 1) -> None:
    """Wait for the pending handler to run.

    A signal is delivered to C first and the Python handler runs at the next
    bytecode boundary, so a test that sends two must let the first land — SIGINT is
    not queued, and two arriving together are seen once.
    """
    deadline = time.monotonic() + TIMEOUT
    while len(reached) < count and time.monotonic() < deadline:
        time.sleep(0.001)
    assert len(reached) >= count, reached


def test_the_step_runs_to_completion_despite_ctrl_c() -> None:
    """Removing a worktree half-way is worse than removing it or not removing it."""
    told: list[str] = []
    finished = False

    with pytest.raises(KeyboardInterrupt), interrupts.deferred(lambda: told.append("noticed")):
        _interrupt_self()
        _settle(told)
        finished = True

    assert finished, "the interrupt must not unwind the step"


def test_the_interrupt_is_raised_once_the_step_is_done() -> None:
    """Deferred, not discarded: the user asked to stop and still means it."""
    with pytest.raises(KeyboardInterrupt), interrupts.deferred(lambda: None):
        _interrupt_self()
        time.sleep(0.01)


def test_the_user_is_told_their_ctrl_c_landed() -> None:
    """Otherwise deferring it is indistinguishable from ignoring it."""
    told: list[str] = []

    with pytest.raises(KeyboardInterrupt), interrupts.deferred(lambda: told.append("noticed")):
        _interrupt_self()
        _settle(told)

    assert told == ["noticed"]


def test_a_second_ctrl_c_stops_waiting() -> None:
    """The first says "I want to stop"; the second says "now"."""
    told: list[str] = []
    reached: list[str] = []

    with pytest.raises(KeyboardInterrupt), interrupts.deferred(lambda: told.append("noticed")):
        _interrupt_self()
        _settle(told)
        _interrupt_self()
        time.sleep(0.01)
        reached.append("the end")

    assert reached == [], "a second Ctrl-C is not deferred"


def test_an_uninterrupted_step_raises_nothing() -> None:
    done: list[str] = []

    with interrupts.deferred(lambda: done.append("never")):
        done.append("worked")

    assert done == ["worked"]


def test_the_previous_handler_is_put_back() -> None:
    """Deferral lasts exactly as long as the step, so a later Ctrl-C is normal."""
    before = signal.getsignal(signal.SIGINT)

    with interrupts.deferred(lambda: None):
        assert signal.getsignal(signal.SIGINT) is not before

    assert signal.getsignal(signal.SIGINT) is before


def test_the_previous_handler_is_put_back_even_when_the_step_fails() -> None:
    before = signal.getsignal(signal.SIGINT)

    with pytest.raises(ZeroDivisionError), interrupts.deferred(lambda: None):
        _ = 1 / 0

    assert signal.getsignal(signal.SIGINT) is before


def test_off_the_main_thread_the_step_still_runs() -> None:
    """Only the main thread may install a handler. Deferring is a nicety; running
    the step is not, so the absence of one must not be an error."""
    done: list[str] = []

    def work() -> None:
        with interrupts.deferred(lambda: None):
            done.append("worked")

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(TIMEOUT)

    assert done == ["worked"]
