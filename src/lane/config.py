"""Configuration: three settings, a version stamp, and getting an old config forward.

Three settings only — `projects_root`, `lanes_root`, `editor`. Adding a fourth is a
decision for the maintainer, not something to slip in. Anything lane remembers for
*convenience* rather than configuration belongs in `state.py` instead.

Two kinds of forward migration are handled, both required rather than optional:

* the bash version's shell-sourced `config` file becomes `config.toml`
* a `config.toml` written by a different version of lane is rewritten in place

Both carry the user's values over, keep a backup, and announce themselves in **one
short line**. What actually changed in the release belongs to its notes on GitHub;
an upgrade notice that grows into a changelog dump is a regression.

**This is the store, not the screen.** `actions/config.py` is the screen that edits it,
and `cli/configuring.py` is the command line that edits it. Both read and write this
module; it knows about neither.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import tomli_w

from lane import buildinfo

APP = "lane"

# The config records a release, not a build: the stamp is compared on every load,
# and a development checkout's version moves with every commit.
CONFIG_VERSION = buildinfo.release()

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


def keep_private(path: Path) -> None:
    """Restrict a file lane wrote to the person who ran lane.

    Every file lane keeps beside the config records where a project keeps things it
    deliberately kept out of git, so this is a stated property rather than tidiness —
    which is exactly why the two platforms' answers are written down here instead of a
    `chmod` being sprinkled over three stores.

    **On POSIX it is the mode, and on Windows it is the profile.** `Path.chmod` on
    Windows toggles a read-only attribute at best: measured on a real runner, after
    `chmod(0o600)` the mode reads back `0o666` and the file is still writable. Windows'
    real access control is the ACL, and the ACL that already covers these files is the
    one on the user's profile — `%APPDATA%` and `%LOCALAPPDATA%` live under
    `C:\\Users\\<you>`, which grants the user, SYSTEM and Administrators and nothing to
    other standard users. That is the same guarantee `0600` gives on macOS, where root
    reads everything too.

    So lane does **not** call `chmod` there, and does not reach for `icacls` or
    `pywin32` to impose a DACL of its own: it would be a new dependency and a second
    copy of a protection the profile already provides. What it does instead is *say so*
    — doctor reports where the protection comes from, and warns when the config has been
    pointed somewhere outside the profile, which is the one way it actually stops
    holding. See `AGENTS.md`, *File permissions are not one thing on two platforms*.
    """
    _restrict(path, _FILE_MODE)


def keep_private_directory(path: Path) -> None:
    """The same decision, for the directory the files sit in."""
    _restrict(path, _DIR_MODE)


def _restrict(path: Path, mode: int) -> None:
    if sys.platform == "win32":
        return
    path.chmod(mode)


def profile_root() -> Path:
    """The directory whose own permissions are what protects lane's files on Windows."""
    return home()


def inside_profile(path: Path) -> bool:
    """Whether `path` sits under the user's profile, and so inherits its permissions.

    Compared as normalised text rather than with `samefile`, for two reasons: the
    directory may not exist yet — this is asked of a config that has never been written
    — and Windows paths are case-insensitive while the two sides come from different
    places, so a case difference between `%APPDATA%` and the profile is ordinary rather
    than a mismatch. `normcase` also settles `/` against `\\`.
    """
    root = os.path.normcase(str(profile_root()))
    candidate = os.path.normcase(str(path))
    return candidate == root or candidate.startswith(root + os.sep)


def config_home() -> Path:
    """Where the settings live: `%APPDATA%` on Windows, XDG everywhere else.

    `${XDG_CONFIG_HOME:-~/.config}` is a Linux convention that *works* on Windows —
    it is only a folder under the user's profile — but no native Windows software uses
    it, so a user who goes looking for lane's settings would not find them where
    everything else on their machine keeps them. `%APPDATA%` is that place, and it is
    the same idea XDG is: per-user, outside the project, followed between machines.

    **An explicitly set `XDG_CONFIG_HOME` wins on every platform**, which is what keeps
    this one code path with a fallback rather than two paths that can drift. The test
    suite is the first user of that, and a Windows user who has one set has said where
    they want it.
    """
    return _home_for("XDG_CONFIG_HOME", "APPDATA", home() / ".config")


def state_home() -> Path:
    """Where the disposable state lives: `%LOCALAPPDATA%` on Windows, XDG elsewhere.

    The same split XDG makes, said the way Windows says it. Roaming follows the user
    between machines and Local does not — and the last project somebody opened a lane in
    is precisely the kind of thing that should follow nobody anywhere.
    """
    return _home_for("XDG_STATE_HOME", "LOCALAPPDATA", home() / ".local" / "state")


def _home_for(xdg_variable: str, windows_variable: str, fallback: Path) -> Path:
    """The chosen base, plus lane's own folder under it.

    The Windows variables are always set by Windows, so the fallback below is the answer
    to "and if it is not" rather than a case anybody meets — and it is the ordinary
    directory under the profile, never an exception.
    """
    asked = os.environ.get(xdg_variable)
    if asked:
        return Path(asked) / APP
    if sys.platform == "win32":
        windows = os.environ.get(windows_variable)
        if windows:
            return Path(windows) / APP
    return fallback / APP


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
        """What the file says, ignoring the environment — what config edits."""
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
        keep_private_directory(self._dir)
        body: dict[str, object] = {"version": CONFIG_VERSION}
        if config.projects_root is not None:
            body["projects_root"] = str(config.projects_root)
        if config.lanes_root is not None:
            body["lanes_root"] = str(config.lanes_root)
        body["editor"] = config.editor
        self.path.write_text(tomli_w.dumps(body), encoding="utf-8")
        keep_private(self.path)

    # -- migration -----------------------------------------------------------
    def _backup(self, path: Path) -> Path:
        backup = Path(f"{path}.bak")
        try:
            backup.write_bytes(path.read_bytes())
            keep_private(backup)
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
