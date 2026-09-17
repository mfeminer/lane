"""Wiring: build the real seams and hand them to the session, or to a subcommand.

The only place the real implementations are chosen. Everything below this module
takes its collaborators as arguments, which is what makes the session testable.

`wire` exists so the two entry points cannot be wired differently. A subcommand gets
the same `Context` the menu gets — same backend, same client, same config, same
problem and the same one-line notice — and differs only in **which `Ui`** it is
handed: the session gets the real one, a subcommand gets one that may already know
some of the answers (`cli.answers.Prefilled`).
"""

from __future__ import annotations

from dataclasses import dataclass

from lane.config import ConfigStore
from lane.context import Context
from lane.environment import Environment
from lane.git.cli_backend import CliGitBackend
from lane.github.gh_client import GhClient
from lane.session import run as run_session
from lane.state import StateStore
from lane.ui.console_ui import ConsoleUi
from lane.ui.seam import Ui


@dataclass(frozen=True, slots=True)
class Wiring:
    """A context, or the reason there is none."""

    context: Context | None
    problem: str | None = None
    notice: str | None = None


def wire(environment: Environment, ui: Ui) -> Wiring:
    config_store = ConfigStore()
    loaded = config_store.load()

    if loaded.problem is not None:
        return Wiring(context=None, problem=loaded.problem)

    return Wiring(
        context=Context(
            ui=ui,
            git=CliGitBackend(),
            github=GhClient(),
            environment=environment,
            config=loaded.config,
            config_store=config_store,
            state_store=StateStore(),
            overridden=loaded.overridden,
        ),
        notice=loaded.notice,
    )


def run(environment: Environment) -> int:
    ui = ConsoleUi()
    wiring = wire(environment, ui)

    if wiring.context is None:
        assert wiring.problem is not None
        ui.error(wiring.problem)
        ui.detail("  Fix or delete that file, then start lane again.")
        return 1

    if wiring.notice is not None:
        # One short line — never a summary of what the release changed.
        ui.detail(wiring.notice)

    # git is checked once, at startup, because nothing lane does works without it.
    # Doctor stays reachable so it can explain the absence.
    git_available = environment.which("git") is not None

    return run_session(wiring.context, git_available=git_available)
