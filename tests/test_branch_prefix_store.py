"""The branch prefixes: a file of lane's own beside the config, never inside it.

Same reasoning as `prepare.toml` (`tests/test_prepare_store.py`): `ConfigStore.save()`
rebuilds the body from the three settings it knows about, so anything else in there is
dropped the first time a version bump rewrites it. An unbounded, editable list of
strings is not a fourth setting either — it has no default to fall back to per value,
no environment override and no validation of its own.
"""

from __future__ import annotations

import stat
from pathlib import Path

from lane.config import ConfigStore
from lane.prefixes import DEFAULT_PREFIXES, BranchPrefixStore


def _store(tmp_path: Path) -> BranchPrefixStore:
    return BranchPrefixStore(tmp_path / "config")


def test_the_file_sits_beside_the_config_and_is_not_the_config(tmp_path: Path) -> None:
    directory = tmp_path / "config"
    store = _store(tmp_path)

    assert store.path == directory / "branch_prefixes.toml"
    assert store.path != ConfigStore(directory).path


def test_with_no_file_at_all_the_six_lane_ships_with_are_what_is_offered(
    tmp_path: Path,
) -> None:
    """Nobody who never opens this screen sees anything change."""
    assert _store(tmp_path).load() == DEFAULT_PREFIXES
    assert DEFAULT_PREFIXES == ("feature", "bugfix", "hotfix", "chore", "refactor", "docs")


def test_an_empty_file_is_the_same_answer_as_no_file(tmp_path: Path) -> None:
    """Forgetting the last prefix leaves a list nothing could be chosen from, so it
    means the same thing as never having customised it at all."""
    store = _store(tmp_path)
    store.save(())

    assert _store(tmp_path).load() == DEFAULT_PREFIXES


def test_a_customised_list_round_trips_and_replaces_the_seed(tmp_path: Path) -> None:
    """Once anything is written down, that *is* the menu — the seed is not merged back
    in, or forgetting one of the six could never stick."""
    store = _store(tmp_path)
    store.save(("feature", "spike", "poc"))

    assert _store(tmp_path).load() == ("feature", "spike", "poc")


def test_the_file_is_private_in_a_private_directory(tmp_path: Path) -> None:
    """Same modes as the config and `prepare.toml`, in the same 0700 directory."""
    store = _store(tmp_path)
    store.save(("feature",))

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


def test_an_unreadable_file_means_the_seed_rather_than_a_crash(tmp_path: Path) -> None:
    """Never an exception and never a rewrite. The six being on screen again is itself
    the signal, exactly as `prepare.toml` asking again is."""
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("prefix = [ this is not toml\n", encoding="utf-8")

    assert store.load() == DEFAULT_PREFIXES
