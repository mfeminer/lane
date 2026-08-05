"""The GitHub client, and the state file.

The suite never authenticates or reaches the network: `gh` is replaced by a script
on PATH that prints what a real `gh` would.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from lane.github.client import CannotTell, Found, NoPullRequest, NotApplicable
from lane.github.gh_client import GhClient
from lane.state import State, StateStore


def _fake_gh(tmp_path: Path, *, stdout: str = "", stderr: str = "", code: int = 0) -> str:
    """A stand-in `gh` on disk. Never contacts GitHub."""
    script = tmp_path / "fake-gh"
    script.write_text(
        f"#!/bin/sh\ncat <<'OUT'\n{stdout}\nOUT\ncat >&2 <<'ERR'\n{stderr}\nERR\nexit {code}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


GITHUB = "git@github.com:acme/thing.git"


# -- G1, G2: the one real question ------------------------------------------------


def test_a_merged_pull_request_is_reported_with_its_number_and_url(tmp_path: Path) -> None:
    gh = _fake_gh(
        tmp_path,
        stdout='{"number": 42, "state": "MERGED", "url": "https://github.com/acme/thing/pull/42"}',
    )

    answer = GhClient(gh).pull_request_for(branch="feature/x", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, Found)
    assert answer.pull_request.number == 42
    assert answer.pull_request.state == "MERGED"
    assert answer.pull_request.url.endswith("/pull/42")


@pytest.mark.parametrize("state", ["OPEN", "CLOSED", "MERGED"])
def test_every_pull_request_state_is_carried_through(tmp_path: Path, state: str) -> None:
    gh = _fake_gh(tmp_path, stdout=f'{{"number": 7, "state": "{state}", "url": "u"}}')

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, Found)
    assert answer.pull_request.state == state


def test_no_pull_request_found(tmp_path: Path) -> None:
    gh = _fake_gh(
        tmp_path,
        stderr='no pull requests found for branch "feature/x"',
        code=1,
    )

    answer = GhClient(gh).pull_request_for(branch="feature/x", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, NoPullRequest)


# -- G3, G4: cannot tell ---------------------------------------------------------


def test_gh_missing_says_how_to_install_it(tmp_path: Path) -> None:
    answer = GhClient("definitely-not-installed-gh").pull_request_for(
        branch="b", remote_url=GITHUB, cwd=tmp_path
    )

    assert isinstance(answer, CannotTell)
    assert answer.reason == "gh-missing"
    assert answer.remedy == "brew install gh"


def test_gh_logged_out_says_how_to_log_in(tmp_path: Path) -> None:
    gh = _fake_gh(
        tmp_path,
        stderr="error: not logged into any GitHub hosts. Run gh auth login to authenticate.",
        code=4,
    )

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, CannotTell)
    assert answer.reason == "gh-logged-out"
    assert answer.remedy == "gh auth login"


def test_an_unreadable_answer_is_cannot_tell_never_a_silent_pass(tmp_path: Path) -> None:
    gh = _fake_gh(tmp_path, stdout="<html>not json</html>")

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, CannotTell)


def test_an_unexplained_failure_is_cannot_tell(tmp_path: Path) -> None:
    gh = _fake_gh(tmp_path, stderr="could not resolve host github.com", code=1)

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, CannotTell)
    assert answer.reason == "gh-failed"


# -- G5, G6: not applicable, without invoking gh ---------------------------------


def test_a_non_github_remote_is_not_applicable_and_gh_is_never_run(tmp_path: Path) -> None:
    """`gh` is deliberately a command that would fail if it were invoked."""
    client = GhClient("definitely-not-installed-gh")

    answer = client.pull_request_for(
        branch="feature/x",
        remote_url="https://contoso.visualstudio.com/X/_git/Y",
        cwd=tmp_path,
    )

    assert isinstance(answer, NotApplicable)
    assert answer.reason == "not-github"


def test_a_detached_lane_is_not_applicable_and_gh_is_never_run(tmp_path: Path) -> None:
    client = GhClient("definitely-not-installed-gh")

    answer = client.pull_request_for(branch=None, remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, NotApplicable)
    assert answer.reason == "detached"


def test_a_repository_with_no_remote_is_not_applicable(tmp_path: Path) -> None:
    client = GhClient("definitely-not-installed-gh")

    answer = client.pull_request_for(branch="b", remote_url=None, cwd=tmp_path)

    assert isinstance(answer, NotApplicable)


# -- E7, E8: convenience state ---------------------------------------------------


def test_state_remembers_the_last_project(xdg: Path) -> None:
    store = StateStore()

    store.remember_project("Acme.Widgets")

    assert store.load().last_project == "Acme.Widgets"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_state_lives_under_xdg_state_home_not_with_the_config(xdg: Path) -> None:
    assert StateStore().path == xdg / "xdg-state" / "lane" / "state.toml"


def test_a_missing_state_file_is_simply_empty(xdg: Path) -> None:
    assert StateStore().load() == State()


def test_a_corrupt_state_file_is_simply_empty(xdg: Path) -> None:
    store = StateStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{{{ not toml")

    assert store.load() == State()


def test_saving_state_never_raises_even_when_it_cannot(xdg: Path, tmp_path: Path) -> None:
    """Losing this file must never interrupt what the user was doing."""
    blocked = tmp_path / "blocked"
    blocked.write_text("I am a file, not a directory")
    store = StateStore(blocked / "lane")

    store.remember_project("anything")  # must not raise

    assert store.load() == State()
