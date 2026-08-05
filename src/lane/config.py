"""Configuration: three settings, a version stamp, and getting an old config forward.

Three settings only — `projects_root`, `lanes_root`, `editor`. Adding a fourth is a
decision for the maintainer, not something to slip in. Anything lane remembers for
*convenience* rather than configuration belongs in `state.py` instead.

Two kinds of forward migration are handled, both required rather than optional:

* the bash version's shell-sourced `config` file becomes `config.toml`
* a `config.toml` written by a different version of lane is rewritten in place

Both carry the user's values over, keep a backup, and announce themselves in **one
short line**. What actually changed belongs to the changelog action; an upgrade
notice that grows into a changelog dump is a regression.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import tomli_w

from lane import __version__

APP = "lane"
CONFIG_VERSION = __version__

DEFAULT_EDITOR = "cursor"
DEFAULT_LANES_DIRNAME = "Lanes"

_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Environment wins over the file. The names are part of lane's interface.
ENV_PROJECTS_ROOT = "LANE_PROJECTS_ROOT"
ENV_LANES_ROOT = "LANE_LANES_ROOT"
ENV_EDITOR = "LANE_EDITOR"


def home() -> Path:
    """Read from the environment each time, so tests can redirect it."""
    return Path(os.environ.get("HOME", str(Path.home())))


def expand_path(text: str) -> Path:
    """`~` and `$VAR` expansion for a path the user typed."""
    stripped = text.strip()
    if stripped == "~":
        return home()
    if stripped.startswith("~/"):
        return home() / stripped[2:]
    expanded = os.path.expandvars(stripped)
    if expanded.startswith("~"):
        return Path(expanded.replace("~", str(home()), 1))
    return Path(expanded)


def config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else home() / ".config"
    return base / APP


def state_home() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else home() / ".local" / "state"
    return base / APP


@dataclass(frozen=True, slots=True)
class Config:
    projects_root: Path | None = None
    lanes_root: Path | None = None
    editor: str = DEFAULT_EDITOR

    def with_defaults(self) -> Config:
        """Fill in what can be defaulted. `projects_root` deliberately cannot be."""
        return replace(
            self,
            lanes_root=self.lanes_root or home() / DEFAULT_LANES_DIRNAME,
            editor=self.editor or DEFAULT_EDITOR,
        )

    @property
    def usable(self) -> bool:
        """Whether lane knows enough to open a lane."""
        return self.projects_root is not None and self.projects_root.is_dir()


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """The config, plus everything the session needs to say about how it got here."""

    config: Config
    exists: bool
    overridden: dict[str, str]
    """setting name -> environment variable currently winning."""

    notice: str | None = None
    """One short line about a migration, or None."""

    problem: str | None = None
    """Set when the file could not be read at all."""


class ConfigStore:
    """Reads and writes the config file. Knows nothing about prompting."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory if directory is not None else config_home()

    @property
    def path(self) -> Path:
        return self._dir / "config.toml"

    @property
    def legacy_path(self) -> Path:
        """The bash version's shell-sourced file."""
        return self._dir / "config"

    # -- reading -------------------------------------------------------------
    def load(self) -> LoadedConfig:
        notice: str | None = None
        problem: str | None = None
        config = Config()
        exists = False

        if self.path.exists():
            try:
                body = tomllib.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                problem = f"Could not read {self.path}: {exc}"
            else:
                exists = True
                config = _from_toml(body)
                if str(body.get("version", "")) != CONFIG_VERSION:
                    notice = self._rewrite_for_this_version(config)
        elif self.legacy_path.exists():
            # The bash version's format. Migrating is required, not optional.
            try:
                config = _from_shell(self.legacy_path.read_text(encoding="utf-8"))
            except OSError as exc:
                problem = f"Could not read {self.legacy_path}: {exc}"
            else:
                exists = True
                notice = self._migrate_from_shell(config)

        overridden = _environment_overrides()
        config = _apply_overrides(config, overridden)
        return LoadedConfig(
            config=config.with_defaults(),
            exists=exists,
            overridden={name: var for name, (var, _) in overridden.items()},
            notice=notice,
            problem=problem,
        )

    def load_file_only(self) -> Config:
        """What the file says, ignoring the environment — what settings edits."""
        if self.path.exists():
            try:
                return _from_toml(tomllib.loads(self.path.read_text(encoding="utf-8")))
            except OSError, tomllib.TOMLDecodeError:
                return Config()
        if self.legacy_path.exists():
            try:
                return _from_shell(self.legacy_path.read_text(encoding="utf-8"))
            except OSError:
                return Config()
        return Config()

    # -- writing -------------------------------------------------------------
    def save(self, config: Config) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dir.chmod(_DIR_MODE)
        body: dict[str, object] = {"version": CONFIG_VERSION}
        if config.projects_root is not None:
            body["projects_root"] = str(config.projects_root)
        if config.lanes_root is not None:
            body["lanes_root"] = str(config.lanes_root)
        body["editor"] = config.editor
        self.path.write_text(tomli_w.dumps(body), encoding="utf-8")
        self.path.chmod(_FILE_MODE)

    # -- migration -----------------------------------------------------------
    def _backup(self, path: Path) -> Path:
        backup = Path(f"{path}.bak")
        try:
            backup.write_bytes(path.read_bytes())
            backup.chmod(_FILE_MODE)
        except OSError:
            pass
        return backup

    def _rewrite_for_this_version(self, config: Config) -> str:
        backup = self._backup(self.path)
        self.save(config)
        return f"Config updated for {APP} {CONFIG_VERSION} · backup: {backup.name}"

    def _migrate_from_shell(self, config: Config) -> str:
        backup = self._backup(self.legacy_path)
        self.save(config)
        return f"Config migrated to TOML for {APP} {CONFIG_VERSION} · backup: {backup.name}"


def _from_toml(body: dict[str, object]) -> Config:
    def path_of(key: str) -> Path | None:
        raw = body.get(key)
        return expand_path(str(raw)) if isinstance(raw, str) and raw.strip() else None

    editor = body.get("editor")
    return Config(
        projects_root=path_of("projects_root"),
        lanes_root=path_of("lanes_root"),
        editor=str(editor) if isinstance(editor, str) and editor.strip() else DEFAULT_EDITOR,
    )


# Matches `NAME="value"` / `NAME=value`, which is all the bash config ever wrote.
_SHELL_ASSIGNMENT = re.compile(r"""^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$""")


def _from_shell(text: str) -> Config:
    """Parse the bash config without sourcing it.

    Executing a shell file to read three strings would be a needless way to run
    arbitrary code, so this reads assignments and ignores everything else.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _SHELL_ASSIGNMENT.match(line)
        if match is None:
            continue
        name, raw = match.group(1), match.group(2).strip()
        # Strip one layer of matching quotes and any trailing comment.
        if raw[:1] in {'"', "'"} and raw[-1:] == raw[:1] and len(raw) >= 2:
            raw = raw[1:-1]
        else:
            raw = raw.split(" #", 1)[0].strip()
        values[name] = raw

    projects = values.get(ENV_PROJECTS_ROOT, "")
    # `LANE_WORKTREES_ROOT` was this setting's name in an earlier build.
    lanes = values.get(ENV_LANES_ROOT) or values.get("LANE_WORKTREES_ROOT", "")
    editor = values.get(ENV_EDITOR, "")
    return Config(
        projects_root=expand_path(projects) if projects else None,
        lanes_root=expand_path(lanes) if lanes else None,
        editor=editor or DEFAULT_EDITOR,
    )


def _environment_overrides() -> dict[str, tuple[str, str]]:
    """setting name -> (variable name, value), for whatever is set right now."""
    found: dict[str, tuple[str, str]] = {}
    for setting, variable in (
        ("projects_root", ENV_PROJECTS_ROOT),
        ("lanes_root", ENV_LANES_ROOT),
        ("editor", ENV_EDITOR),
    ):
        value = os.environ.get(variable, "").strip()
        if value:
            found[setting] = (variable, value)
    return found


def _apply_overrides(config: Config, overrides: dict[str, tuple[str, str]]) -> Config:
    updated = config
    if "projects_root" in overrides:
        updated = replace(updated, projects_root=expand_path(overrides["projects_root"][1]))
    if "lanes_root" in overrides:
        updated = replace(updated, lanes_root=expand_path(overrides["lanes_root"][1]))
    if "editor" in overrides:
        updated = replace(updated, editor=overrides["editor"][1])
    return updated
