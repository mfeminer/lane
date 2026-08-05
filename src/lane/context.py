"""What an action is given: the four seams plus the configuration.

The prompt layer is *passed in* rather than the action being handed a finished set
of answers, because some questions genuinely cannot be gathered up front — closing
a lane only knows what to confirm after it has fetched and run its checks. The rule
that matters is that the action does not know *how* the asking happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lane.config import Config, ConfigStore
from lane.environment import Environment
from lane.git.backend import GitBackend
from lane.github.client import GitHubClient
from lane.lanes import LaneStore
from lane.state import StateStore
from lane.ui.seam import Ui


@dataclass
class Context:
    ui: Ui
    git: GitBackend
    github: GitHubClient
    environment: Environment
    config: Config
    config_store: ConfigStore
    state_store: StateStore
    overridden: dict[str, str] = field(default_factory=dict)
    """setting name -> environment variable currently winning over the file."""

    def lane_store(self) -> LaneStore:
        root = self.config.lanes_root
        if root is None:  # pragma: no cover - with_defaults() always fills this in
            raise RuntimeError("lanes_root is not configured")
        return LaneStore(root)

    @property
    def projects_root(self) -> Path | None:
        return self.config.projects_root

    def reload_config(self) -> None:
        """After settings has written the file."""
        loaded = self.config_store.load()
        self.config = loaded.config
        self.overridden = loaded.overridden
