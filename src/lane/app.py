"""Wiring: build the real seams and hand them to the session.

The only place the real implementations are chosen. Everything below this module
takes its collaborators as arguments, which is what makes the session testable.
"""

from __future__ import annotations

from lane.config import ConfigStore
from lane.context import Context
from lane.environment import Environment
from lane.git.cli_backend import CliGitBackend
from lane.github.gh_client import GhClient
from lane.session import run as run_session
from lane.state import StateStore
from lane.ui.console_ui import ConsoleUi


def run(environment: Environment) -> int:
    ui = ConsoleUi()
    config_store = ConfigStore()
    loaded = config_store.load()

    if loaded.problem is not None:
        ui.error(loaded.problem)
        ui.detail("  Fix or delete that file, then start lane again.")
        return 1

    if loaded.notice is not None:
        # One short line. The changelog is its own action.
        ui.detail(loaded.notice)

    context = Context(
        ui=ui,
        git=CliGitBackend(),
        github=GhClient(),
        environment=environment,
        config=loaded.config,
        config_store=config_store,
        state_store=StateStore(),
        overridden=loaded.overridden,
    )

    # git is checked once, at startup, because nothing lane does works without it.
    # Doctor stays reachable so it can explain the absence.
    git_available = environment.which("git") is not None

    return run_session(context, git_available=git_available)
