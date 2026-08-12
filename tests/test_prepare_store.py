"""Where the answers live: a sibling of the config file, never inside it.

Why a second file rather than three more keys in `config.toml`: `ConfigStore.save()`
rebuilds the body from the three settings it knows about, so anything else in there is
dropped the first time a version bump rewrites it. Its migration code is the one part
of the config that must never be wrong, and it does not need a second job.
"""

from __future__ import annotations

import stat
from pathlib import Path

from lane.config import ConfigStore
from lane.prepare import Step, Verb
from lane.prepare.store import PrepareStore


def _store(tmp_path: Path) -> PrepareStore:
    return PrepareStore(tmp_path / "config")


def test_the_file_sits_beside_the_config_and_is_not_the_config(tmp_path: Path) -> None:
    directory = tmp_path / "config"
    store = _store(tmp_path)

    assert store.path == directory / "prepare.toml"
    assert store.path != ConfigStore(directory).path


def test_every_verb_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    steps = (
        Step(project="acme", verb=Verb.CLONE, path="apps/web/node_modules"),
        Step(project="acme", verb=Verb.CLONE, path="node_modules", refresh=True),
        Step(project="acme", verb=Verb.LINK, path="apps/web/.env"),
        Step(project="acme", verb=Verb.SKIP, path="apps/console/dist"),
        Step(
            project="acme",
            verb=Verb.RUN,
            command="yarn install",
            directory="apps/web",
            unless="apps/web/node_modules",
        ),
        Step(project="other", verb=Verb.CLONE, path="vendor"),
    )
    store.save(steps)

    assert _store(tmp_path).load().steps == steps


def test_the_file_is_private_in_a_private_directory(tmp_path: Path) -> None:
    """It records which paths a project keeps outside git, which is a description of
    where that project's secrets are. Same modes as the config for the same reason."""
    store = _store(tmp_path)
    store.save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


def test_a_missing_file_means_nothing_is_remembered(tmp_path: Path) -> None:
    loaded = _store(tmp_path).load()
    assert loaded.steps == ()
    assert loaded.problem is None


def test_an_unreadable_file_means_nothing_is_remembered_and_says_so(tmp_path: Path) -> None:
    """Never an exception and never a rewrite. The screen then asks again, which is
    itself the signal, and doctor names the file."""
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("this is not toml [[[")

    loaded = store.load()

    assert loaded.steps == ()
    assert loaded.problem is not None
    assert str(store.path) in loaded.problem


def test_an_unknown_verb_and_an_unknown_key_are_ignored(tmp_path: Path) -> None:
    """So a file written by a later lane still loads in an earlier one."""
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(
        "\n".join(
            (
                'version = "9.9.9"',
                "[[step]]",
                'project = "acme"',
                'verb = "teleport"',
                'path = "node_modules"',
                "",
                "[[step]]",
                'project = "acme"',
                'verb = "clone"',
                'path = "vendor"',
                'something_new = "later"',
            )
        )
    )

    loaded = store.load()

    assert loaded.steps == (Step(project="acme", verb=Verb.CLONE, path="vendor"),)
    assert loaded.problem is None


def test_a_step_with_nothing_to_act_on_is_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text('[[step]]\nproject = "acme"\nverb = "clone"\n')

    assert store.load().steps == ()


def test_steps_are_looked_up_by_project_name(tmp_path: Path) -> None:
    """The identifier lane already uses everywhere — `Lane.project`,
    `<lanes_root>/<project>`, the listing's grouping. A path would be a string
    comparison of paths, which is the thing `samefile` exists to avoid."""
    store = _store(tmp_path)
    store.save(
        (
            Step(project="acme", verb=Verb.CLONE, path="node_modules"),
            Step(project="other", verb=Verb.SKIP, path="vendor"),
        )
    )

    loaded = store.load()

    assert [step.path for step in loaded.for_project("acme")] == ["node_modules"]
    assert loaded.for_project("renamed-acme") == ()


def test_remembering_a_project_replaces_only_that_projects_answers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        (
            Step(project="acme", verb=Verb.CLONE, path="node_modules"),
            Step(project="other", verb=Verb.SKIP, path="vendor"),
        )
    )

    store.remember(
        "acme",
        (
            Step(project="acme", verb=Verb.SKIP, path="node_modules"),
            Step(project="acme", verb=Verb.LINK, path=".env"),
        ),
    )

    loaded = store.load()
    assert [(step.path, step.verb) for step in loaded.for_project("acme")] == [
        ("node_modules", Verb.SKIP),
        (".env", Verb.LINK),
    ]
    assert [step.path for step in loaded.for_project("other")] == ["vendor"]


def test_forgetting_a_step_leaves_the_others(tmp_path: Path) -> None:
    store = _store(tmp_path)
    keep = Step(project="acme", verb=Verb.CLONE, path="vendor")
    drop = Step(project="acme", verb=Verb.SKIP, path="node_modules")
    store.save((keep, drop))

    store.forget(drop)

    assert store.load().steps == (keep,)
