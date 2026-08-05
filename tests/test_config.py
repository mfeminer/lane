"""Configuration and convenience state.

The filesystem runs for real here — only where XDG points is redirected — so file
modes and directory creation are genuinely exercised.
"""

from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import pytest

from lane import config as config_module
from lane.config import Config, ConfigStore

# -- location and permissions (E1) -----------------------------------------------


def test_config_lives_under_xdg_config_home(xdg: Path) -> None:
    store = ConfigStore()
    assert store.path == xdg / "xdg-config" / "lane" / "config.toml"


def test_config_falls_back_to_dot_config_when_xdg_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert ConfigStore().path == tmp_path / ".config" / "lane" / "config.toml"


def test_saving_creates_a_private_directory_and_file(xdg: Path) -> None:
    store = ConfigStore()

    store.save(Config(projects_root=Path("/p"), lanes_root=Path("/l"), editor="cursor"))

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


# -- round trip (E2) -------------------------------------------------------------


def test_settings_round_trip_through_toml(xdg: Path) -> None:
    store = ConfigStore()
    saved = Config(
        projects_root=Path("/Users/x/Projects"),
        lanes_root=Path("/Users/x/Lanes"),
        editor="zed",
    )

    store.save(saved)
    loaded = store.load()

    assert loaded.config.projects_root == saved.projects_root
    assert loaded.config.lanes_root == saved.lanes_root
    assert loaded.config.editor == "zed"
    # The version stamp is written so a later lane can tell it must migrate.
    body = tomllib.loads(store.path.read_text())
    assert body["version"] == config_module.CONFIG_VERSION


def test_a_missing_config_reports_itself_as_absent(xdg: Path) -> None:
    loaded = ConfigStore().load()
    assert not loaded.exists


# -- environment overrides (E3) --------------------------------------------------


def test_environment_overrides_the_file(xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ConfigStore()
    store.save(Config(projects_root=Path("/from/file"), lanes_root=Path("/l"), editor="cursor"))
    monkeypatch.setenv("LANE_PROJECTS_ROOT", "/from/env")
    monkeypatch.setenv("LANE_EDITOR", "code")

    loaded = store.load()

    assert loaded.config.projects_root == Path("/from/env")
    assert loaded.config.editor == "code"
    assert loaded.config.lanes_root == Path("/l"), "un-overridden values still come from the file"


def test_overrides_are_named_so_settings_can_say_the_environment_is_winning(
    xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANE_LANES_ROOT", "/from/env")

    loaded = ConfigStore().load()

    assert loaded.overridden == {"lanes_root": "LANE_LANES_ROOT"}


def test_the_file_keeps_its_own_value_when_the_environment_wins(
    xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings edits the file, not the environment."""
    store = ConfigStore()
    store.save(Config(projects_root=Path("/file/p"), lanes_root=Path("/file/l"), editor="cursor"))
    monkeypatch.setenv("LANE_EDITOR", "vim")

    assert store.load().config.editor == "vim"
    assert store.load_file_only().editor == "cursor"


# -- migration from the shell format (E4) ----------------------------------------


def test_a_shell_sourced_config_is_migrated_to_toml(xdg: Path) -> None:
    """The bash version's config was sourced by the shell. It must carry over."""
    store = ConfigStore()
    legacy = store.legacy_path
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        "# lane configuration\n"
        'LANE_CONFIG_VERSION="0.0.1"\n'
        'LANE_PROJECTS_ROOT="/Users/x/Acme/Projects"\n'
        'LANE_LANES_ROOT="/Users/x/Lanes"\n'
        'LANE_EDITOR="cursor"\n'
    )

    loaded = store.load()

    assert loaded.exists
    assert loaded.config.projects_root == Path("/Users/x/Acme/Projects")
    assert loaded.config.lanes_root == Path("/Users/x/Lanes")
    assert loaded.config.editor == "cursor"
    assert store.path.exists(), "migration writes the TOML file"
    assert loaded.notice, "migration announces itself"


def test_migration_carries_the_old_worktrees_root_name_over(xdg: Path) -> None:
    """`LANE_WORKTREES_ROOT` was renamed to `LANE_LANES_ROOT` in an earlier build."""
    store = ConfigStore()
    store.legacy_path.parent.mkdir(parents=True, exist_ok=True)
    store.legacy_path.write_text(
        'LANE_PROJECTS_ROOT="/p"\nLANE_WORKTREES_ROOT="/old/lanes"\nLANE_EDITOR="code"\n'
    )

    loaded = store.load()

    assert loaded.config.lanes_root == Path("/old/lanes")


def test_migration_keeps_a_backup_of_the_shell_config(xdg: Path) -> None:
    store = ConfigStore()
    store.legacy_path.parent.mkdir(parents=True, exist_ok=True)
    store.legacy_path.write_text('LANE_PROJECTS_ROOT="/p"\n')

    store.load()

    assert (
        store.legacy_path.with_suffix(".bak").exists()
        or Path(str(store.legacy_path) + ".bak").exists()
    )


def test_shell_config_expands_home_and_variables(xdg: Path) -> None:
    store = ConfigStore()
    store.legacy_path.parent.mkdir(parents=True, exist_ok=True)
    store.legacy_path.write_text('LANE_PROJECTS_ROOT="$HOME/Projects"\nLANE_LANES_ROOT="~/Lanes"\n')

    loaded = store.load()

    home = Path(str(xdg / "home"))
    assert loaded.config.projects_root == home / "Projects"
    assert loaded.config.lanes_root == home / "Lanes"


# -- version rewrite (E5) --------------------------------------------------------


def test_a_config_from_another_version_is_rewritten_with_a_backup(xdg: Path) -> None:
    store = ConfigStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        'version = "0.0.0-old"\nprojects_root = "/p"\nlanes_root = "/l"\neditor = "subl"\n'
    )

    loaded = store.load()

    assert loaded.config.editor == "subl", "values carry over"
    assert tomllib.loads(store.path.read_text())["version"] == config_module.CONFIG_VERSION
    assert Path(str(store.path) + ".bak").exists(), "a backup is kept"


def test_the_upgrade_notice_is_one_short_line(xdg: Path) -> None:
    """Never a changelog dump — the changelog is its own action."""
    store = ConfigStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('version = "0.0.0-old"\nprojects_root = "/p"\n')

    notice = store.load().notice

    assert notice is not None
    assert "\n" not in notice.strip()
    assert len(notice) < 120


def test_a_config_of_the_current_version_is_left_alone(xdg: Path) -> None:
    store = ConfigStore()
    store.save(Config(projects_root=Path("/p"), lanes_root=Path("/l"), editor="cursor"))
    before = store.path.read_text()

    loaded = store.load()

    assert loaded.notice is None
    assert store.path.read_text() == before


def test_a_corrupt_config_is_reported_rather_than_crashing(xdg: Path) -> None:
    store = ConfigStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("this is not toml {{{")

    loaded = store.load()

    assert loaded.problem is not None


# -- path expansion (E6) ---------------------------------------------------------


def test_typed_paths_expand_home(xdg: Path) -> None:
    home = xdg / "home"
    assert config_module.expand_path("~/Projects") == home / "Projects"
    assert config_module.expand_path("~") == home
    assert config_module.expand_path("/absolute/path") == Path("/absolute/path")


def test_expansion_trims_surrounding_whitespace(xdg: Path) -> None:
    assert config_module.expand_path("  ~/Projects  ") == xdg / "home" / "Projects"
