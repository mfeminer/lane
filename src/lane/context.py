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
from lane.prefixes import BranchPrefixStore
from lane.prepare.store import PrepareStore
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

    def prepare_store(self) -> PrepareStore:
        """The preparation answers, which live beside the config file by definition.

        Derived from `config_store` rather than injected: `prepare.toml` is a sibling of
        `config.toml`, so a second field could only ever disagree with it — and a test
        that redirected one and forgot the other would write into the real home.
        """
        return PrepareStore(self.config_store.path.parent)

    def prefix_store(self) -> BranchPrefixStore:
        """The branch prefixes, a second sibling of the config file.

        Derived from `config_store` for the same reason `prepare_store` is: it lives
        beside `config.toml` by definition, so a field of its own could only ever
        disagree with it.
        """
        return BranchPrefixStore(self.config_store.path.parent)

    def lane_store(self) -> LaneStore:
        root = self.config.lanes_root
        if root is None:  # pragma: no cover - with_defaults() always fills this in
            raise RuntimeError("lanes_root is not configured")
        return LaneStore(root)

    @property
    def projects_root(self) -> Path | None:
        return self.config.projects_root

    def reload_config(self) -> None:
        """After config has written the file."""
        loaded = self.config_store.load()
        self.config = loaded.config
        self.overridden = loaded.overridden
