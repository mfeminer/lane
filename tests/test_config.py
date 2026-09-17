"""Configuration and convenience state.

The filesystem runs for real here — only where XDG points is redirected — so file
modes and directory creation are genuinely exercised.
"""

from __future__ import annotations

import stat
import sys
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


def test_windows_puts_the_config_where_windows_software_puts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`~/.config` is a Linux convention. Nothing stops it working on Windows — it is
    only a folder under the user's profile — but no native Windows tool uses it, so a
    user looking for lane's settings would not find them where everything else keeps
    them. `%APPDATA%` is that place, and it is what `XDG_CONFIG_HOME` means here."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    assert ConfigStore().path == tmp_path / "Roaming" / "lane" / "config.toml"


def test_windows_keeps_disposable_state_out_of_the_roaming_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same split XDG makes, said the way Windows says it: Roaming follows the user
    between machines, Local does not — and the last project you opened a lane in is
    exactly the kind of thing that should not follow anybody anywhere."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert config_module.state_home() == tmp_path / "Local" / "lane"


def test_an_explicit_xdg_setting_still_wins_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody who has set it has said where they want it, and the test suite is one
    of them — which is what keeps this one code path rather than two."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "asked-for"))

    assert ConfigStore().path == tmp_path / "asked-for" / "lane" / "config.toml"


def test_appdata_means_nothing_off_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It can be set by a shell someone shares between machines. It is not a macOS or
    Linux convention and must not quietly become one."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("HOME", str(tmp_path))

    assert ConfigStore().path == tmp_path / ".config" / "lane" / "config.toml"


def test_windows_without_appdata_still_has_somewhere_to_put_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows always sets it, so this is the answer to "and if it doesn't" rather than
    a case anybody meets: the same fallback every other platform uses, which is a real
    directory under the profile and never an exception."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert ConfigStore().path == tmp_path / ".config" / "lane" / "config.toml"


def test_saving_creates_a_private_directory_and_file(xdg: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("modes mean nothing here — see the Windows tests below")
    store = ConfigStore()

    store.save(Config(projects_root=Path("/p"), lanes_root=Path("/l"), editor="cursor"))

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


def test_windows_is_not_given_a_mode_that_would_do_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured on a real Windows runner: after `chmod(0o600)` the mode reads back
    `0o666` and the file is still writable. `Path.chmod` there toggles a read-only
    attribute at best — it is not the access control Windows actually uses. Calling it
    anyway would be code that looks like a security measure and is not one, which is
    worse than not calling it: see `AGENTS.md`, *File permissions*."""

    def refuse(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("chmod says nothing on Windows and must not be called")

    written = tmp_path / "config.toml"
    written.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "chmod", refuse)

    config_module.keep_private(written)
    config_module.keep_private_directory(tmp_path)


def test_everywhere_else_the_mode_is_still_set(tmp_path: Path) -> None:
    """The other half of the same decision: nothing about Windows loosens POSIX."""
    if sys.platform == "win32":
        pytest.skip("POSIX modes")
    written = tmp_path / "config.toml"
    written.write_text("x = 1\n", encoding="utf-8")

    config_module.keep_private(written)
    config_module.keep_private_directory(tmp_path)

    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_only_one_place_in_lane_decides_how_a_written_file_is_protected() -> None:
    """Four stores write files describing where a project keeps things it kept out of
    git, and they must not each carry their own opinion about protecting them: a fifth
    store should inherit the decision rather than rediscover it. Counted, not eyeballed
    — a `chmod` added back to any of them is a Windows no-op that reads like a
    safeguard."""
    import inspect

    from lane import prefixes, state
    from lane.prepare import store as prepare_store

    for module in (state, prepare_store, prefixes):
        assert ".chmod(" not in inspect.getsource(module), (
            f"{module.__name__} should ask config.keep_private"
        )
    assert inspect.getsource(config_module).count(".chmod(") == 1, (
        "only config._restrict sets a mode"
    )


# -- round trip (E2) -------------------------------------------------------------


def test_the_three_settings_round_trip_through_toml(xdg: Path) -> None:
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


def test_overrides_are_named_so_config_can_say_the_environment_is_winning(
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
    """Never a changelog dump — what changed lives in the release notes."""
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
